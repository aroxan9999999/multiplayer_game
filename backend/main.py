from fastapi import FastAPI, Request, Form, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from models import User, Base, Game
from database import engine, SessionLocal
from passlib.context import CryptContext
from typing import Optional, Dict, Any, List
from starlette.middleware.sessions import SessionMiddleware
import secrets
from pydantic import BaseModel
from functools import wraps
from utils import LobbyManager, GameManager
import json
import logging
from datetime import datetime

# --- Конфигурация приложения ---
app = FastAPI(title="Color Grid Game", description="Многопользовательская игра с закрашиванием клеток")

# Конфигурация сессии
SESSION_DURATION = 3600 * 60  # 1 час

# Middleware для сессий
app.add_middleware(
    SessionMiddleware,
    secret_key=secrets.token_hex(32),
    session_cookie="session_id",
    https_only=False,
    max_age=SESSION_DURATION
)

# Подключение статических файлов
app.mount("/static", StaticFiles(directory="../frontend"), name="static")
templates = Jinja2Templates(directory="../frontend")

# --- Настройки безопасности ---
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# --- Модели данных ---
class UserSessionData(BaseModel):
    id: int
    username: str
    is_active: bool

# --- Инициализация БД ---
Base.metadata.create_all(bind=engine)

# --- Вспомогательные функции ---
def get_db():
    """Генератор сессий БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Получает пользователя из БД по username из сессии"""
    username = request.session.get("username")
    if not username:
        return None
    return db.query(User).filter(User.username == username).first()

def login_required(func):
    """Декоратор для проверки аутентификации"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = get_current_user(request, next(get_db()))
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        return await func(request, *args, **kwargs)
    return wrapper

# --- Маршруты ---
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Перенаправление на лобби"""
    return RedirectResponse(url="/lobby")

@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    """Форма регистрации"""
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register", response_class=RedirectResponse)
async def register_user(
        request: Request,
        username: str = Form(..., min_length=3, max_length=50),
        password: str = Form(..., min_length=2),
        db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(
            status_code=400,
            detail="Username already taken"
        )

    try:
        new_user = User(
            username=username,
            password_hash=pwd_context.hash(password),
            date_registration=datetime.utcnow()
        )
        db.add(new_user)
        db.commit()

        request.session["username"] = username
        return RedirectResponse(url="/profile", status_code=303)

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Registration failed: {str(e)}"
        )

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """Форма входа"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=RedirectResponse)
async def login_user(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    """Аутентификация пользователя"""
    user = db.query(User).filter(User.username == username).first()

    if not user or not pwd_context.verify(password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    request.session.update({
        "username": user.username,
        "user_data": {
            "id": user.id,
            "username": user.username,
        }
    })

    return RedirectResponse(url="/profile", status_code=303)

@app.get("/profile", response_class=HTMLResponse)
@login_required
async def profile(request: Request, db: Session = Depends(get_db)):
    """Страница профиля с игровой статистикой"""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    lobby = LobbyManager(db)
    stats = await lobby.get_user_stats(current_user.username)

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": current_user,
        "stats": stats if stats["status"] == 200 else None
    })

@app.get("/lobby", response_class=HTMLResponse)
@login_required
async def lobby_page(request: Request, db: Session = Depends(get_db)):
    """Страница лобби с игровым интерфейсом"""
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    lobby = LobbyManager(db)
    game = await lobby.get_or_create_game()

    # Проверяем, находится ли пользователь уже в игре
    player_data = next(
        (p.split(":") for p in game.game_players
         if p.startswith(current_user.username + ":")),
        None
    )

    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": current_user.username,
        "is_active": 1 if player_data else 0,
        "count":len(game.game_players),
        "color": player_data[1] if player_data else None,
        "game_id": game.id,
        "available_colors": [c for c in LobbyManager.COLOR_PALETTE
                            if not any(c in p for p in game.game_players)]
    })

@app.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    """Выход из системы"""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

connected_clients: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(
        websocket: WebSocket,
        db: Session = Depends(get_db)
):
    await websocket.accept()
    connected_clients.append(websocket)

    lobby = LobbyManager(db)
    current_game = None

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "join":
                username = data.get("username")
                color = data.get("color")

                if not username or not color:
                    await websocket.send_json({"error": "Username and color required"})
                    continue

                current_game = await lobby.get_or_create_game()
                result = await lobby.add_player(current_game.id, username, color)

                if result["status"] != 200:
                    await websocket.send_json({"error": result.get("message")})
                    continue

                # Рассылаем всем клиентам обновление лобби
                lobby_update = {
                    "type": "lobby_update",
                    "game_id": current_game.id,
                    **result
                }

                await broadcast_to_all(lobby_update)

                # Проверка готовности к старту
                start_check = await lobby.start_game_check(current_game.id)
                if start_check["status"] == 200:
                    game_manager = GameManager(db, current_game.id)

                    await broadcast_to_all({
                        "type": "game_start",
                        **start_check
                    })

    except WebSocketDisconnect:
        logging.info("WebSocket disconnected")
        if websocket in connected_clients:
            connected_clients.remove(websocket)

    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        await websocket.send_json({
            "error": str(e),
            "type": "error"
        })
async def broadcast_to_all(message: dict):
    disconnected_clients = []
    for client in connected_clients:
        try:
            await client.send_json(message)
        except Exception as e:
            logging.warning(f"Client disconnected or error sending: {e}")
            disconnected_clients.append(client)
    # Удаляем мёртвые сокеты
    for dc in disconnected_clients:
        connected_clients.remove(dc)


game_connections = {}  # {game_id: set(websocket1, websocket2...)}


@app.get("/game/{game_id}", response_class=HTMLResponse)
@login_required
async def game_page(request: Request, game_id: str, db: Session = Depends(get_db)):
    # Получаем текущего пользователя
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        # Создаем менеджер игры
        game_manager = GameManager(db, int(game_id))

        # Получаем данные игры
        init_result = game_manager.init_data()

        # Проверяем успешность получения данных
        if "status" in init_result and init_result["status"] != 200:
            raise HTTPException(status_code=init_result["status"],
                                detail=init_result.get("error", "Ошибка при получении данных игры"))


        return templates.TemplateResponse("game.html", {
            "request": request,
            "game_id": game_id,
            "username": current_user.username,
            "players_data": init_result.get("players", []),
            "game_state": init_result.get("game_state", {})
        })

    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный ID игры")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/game/{game_id}/ws")
async def game_websocket_endpoint( websocket: WebSocket, game_id: str,db: Session = Depends(get_db)):
    await websocket.accept()

    # Добавляем соединение в словарь игр
    if game_id not in game_connections:
        game_connections[game_id] = set()
    game_connections[game_id].add(websocket)

    try:
        game_manager = GameManager(db, int(game_id))

        while True:
            data = await websocket.receive_json()

            if data.get("action") == "click":
                username = data.get("username")
                coord = data.get("coord")

                if not username or not coord:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Требуются username и coord"
                    })
                    continue

                # Регистрируем клик
                click_result = await game_manager.register_click(username, coord)

                # Отправляем результат клика
                await broadcast_to_game(game_id, {
                    "type": "click_result",
                    "data": click_result
                })

                # Проверяем завершение игры
                finish_result = await game_manager.check_finish_game()
                if finish_result:  # Если игра завершена
                    await broadcast_to_game(game_id, {
                        "type": "finish_game",
                        "data": finish_result
                    })
                    break  # Завершаем соединение

    except WebSocketDisconnect:
        game_connections[game_id].discard(websocket)
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
    finally:
        game_connections[game_id].discard(websocket)

async def broadcast_to_game(game_id: str, message: dict):
    if game_id not in game_connections:
        return

    disconnected = []
    for ws in game_connections[game_id]:
        try:
            await ws.send_json(message)
        except:
            disconnected.append(ws)

    for ws in disconnected:
        game_connections[game_id].discard(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)