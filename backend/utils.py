# utils/game_objects.py
from typing import Dict, List, Optional, Any, Tuple
from sqlalchemy.orm import Session
from models import Game, User, UserState
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from collections import Counter

# Настройка логирования
logger = logging.getLogger(__name__)
handler = RotatingFileHandler("game_process.log", maxBytes=1_000_000, backupCount=5)
formatter = logging.Formatter('[%(asctime)s] %(levelname)s — %(message)s')
handler.setFormatter(formatter)
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False

class BaseGameManager:
    """Базовый класс для управления игрой с общими методами"""

    def __init__(self, db: Session):
        self.db = db

    async def get_user_stats(self, username: str) -> Dict[str, Any]:
        """
        Получает полную статистику игрока
        Returns:
            {
                "status": 200/404/500,
                "username": str,
                "total_games": int,
                "total_clicks": int,
                "success_clicks": int,
                "failed_clicks": int,
                "wins_count": int,
                "most_used_color": str,
                "registration_date": str,
                "colors_used": List[str]
            }
        """
        try:
            user = self.db.query(User).filter(User.username == username).first()
            if not user:
                return {"status": 404, "error": "User not found"}

            # Calculate color statistics safely
            color_stats = Counter(user.color_used)
            most_common_color = color_stats.most_common(1)[0][0] if user.color_used else None

            # Calculate failed clicks
            failed_clicks = max(0, user.total_clicks - user.success_clicks)

            return {
                "status": 200,
                "username": user.username,
                "total_games": user.total_games,
                "total_clicks": user.total_clicks,
                "success_clicks": user.success_clicks,
                "failed_clicks": failed_clicks,  # Fixed typo in key name
                "wins_count": user.wins_count,
                "most_used_color": most_common_color,
                "registration_date": user.date_registration.isoformat(),
                "colors_used": user.color_used
            }
        except Exception as e:
            logger.error(f"Error getting stats for {username}: {e}")
            return {"status": 500, "error": "Internal server error"}

class LobbyManager(BaseGameManager):
    """Управление лобби: создание игры, добавление игроков, старт игры"""

    COLOR_PALETTE = [
        "#FF0000", "#00FF00", "#0000FF", "#FFFF00",  # Красный, Зеленый, Синий, Желтый
        "#FF00FF", "#00FFFF", "#800000", "#008000",  # Пурпурный, Бирюзовый, Темно-красный, Темно-зеленый
        "#000080", "#808000", "#800080", "#008080",  # Темно-синий, Оливковый, Фиолетовый, Темно-бирюзовый
        "#C0C0C0", "#808080", "#FFA500", "#A52A2A"  # Серебряный, Серый, Оранжевый, Коричневый
    ]

    def __init__(self, db: Session):
        super().__init__(db)

    async def get_or_create_game(self) -> Tuple[Game, bool]:
        """
        Находит ожидающую игру или создает новую
        Returns:
            (Game, created) - игра и флаг создания новой
        """
        try:
            game = self.db.query(Game).filter(Game.is_active == False).first()
            if game:
                return game

            new_game = Game(
                is_active=False,
                started_at=datetime.utcnow(),
                game_players=[],
                clicked_cells=[],
                total_clicks=0,
                winners=[],
                game_state={
                    "state": "waiting",
                    "players": [],
                    "available_colors": self.COLOR_PALETTE.copy()
                }
            )
            self.db.add(new_game)
            self.db.commit()
            self.db.refresh(new_game)
            return new_game

        except Exception as e:
            logger.error(f"Error creating game: {e}")
            self.db.rollback()
            raise

    async def add_player(self, game_id: int, username: str, color: str) -> Dict:
        """
        Добавляет игрока с выбранным цветом в лобби
        Returns:
            {
                "status": 200/400/404/500,
                "game_id": int,
                "players_count": int,
                "players": List[Tuple[name, color]],
                "available_colors": List[str]
            }
        """
        try:
            if color not in self.COLOR_PALETTE:
                return {"status": 400, "message": "Неверный цвет"}

            game = self.db.query(Game).get(game_id)
            if not game:
                return {"status": 404, "message": "Игра не найдена"}

            user = self.db.query(User).filter(User.username == username).first()
            if not user:
                return {"status": 404, "message": "Пользователь не найден"}

            for player in game.game_players:
                name, clr = player.split(":")
                if clr == color:
                    return {"status": 400, "message": "Цвет уже занят"}
                if name == username:
                    return {"status": 400, "message": "Игрок уже в лобби"}

            game.game_players.append(f"{username}:{color}")
            game.game_state["players"].append({
                "username": username,
                "color": color,
                "ready": False
            })
            user.color = color
            game.game_state["available_colors"].remove(color)
            print(user.username)
            players = game.game_players or []
            print(type(players))
            if f"{user.username}:{color}" not in players:
                players.append(f"{user.username}:{color}")
                game.game_players = players  # <--- вот это нужно обязательно

            self.db.commit()
            print(game.game_players)
            return {
                "status": 200,
                "game_id": game.id,
                "players_count": len(game.game_players),
                "players": [p.split(":") for p in game.game_players],
                "available_colors": game.game_state["available_colors"]
            }

        except Exception as e:
            logger.error(f"Error adding player {username}: {e}")
            self.db.rollback()
            return {"status": 500, "message": "Ошибка сервера"}

    async def remove_player(self, game_id: int, username: str) -> Dict:
        """
        Удаляет игрока из лобби
        Returns:
            {
                "status": 200/404/500,
                "message": str,
                "removed_color": str,
                "available_colors": List[str]
            }
        """
        try:
            game = self.db.query(Game).get(game_id)
            if not game:
                return {"status": 404, "message": "Игра не найдена"}

            user = self.db.query(User).filter(User.username == username).first()
            if not user:
                return {"status": 404, "message": "Пользователь не найден"}

            removed_color = None
            new_players = []
            for p in game.game_players:
                name, clr = p.split(":")
                if name != username:
                    new_players.append(p)
                else:
                    removed_color = clr

            if removed_color is None:
                return {"status": 404, "message": "Игрок не найден в лобби"}

            game.game_players = new_players
            game.game_state["players"] = [
                p for p in game.game_state["players"]
                if p["username"] != username
            ]
            game.game_state["available_colors"].append(removed_color)

            if user in game.players:
                game.players.remove(user)

            self.db.commit()

            return {
                "status": 200,
                "message": "Игрок удален",
                "removed_color": removed_color,
                "available_colors": game.game_state["available_colors"]
            }

        except Exception as e:
            logger.error(f"Error removing player {username}: {e}")
            self.db.rollback()
            return {"status": 500, "message": "Ошибка сервера"}

    async def start_game_check(self, game_id: int) -> Dict:
        """
        Проверяет готовность игры к старту (4 уникальных игрока)
        Returns:
            {
                "status": 200/400/404/500,
                "game_id": int,
                "start_time": str,
                "players": List[Tuple[name, color]]
            }
        """
        try:
            game = self.db.query(Game).get(game_id)
            if not game:
                return {"status": 404, "message": "Игра не найдена"}

            # Проверка условий старта
            if len(game.game_players) != 2 or len({p.split(":")[1] for p in game.game_players}) != 2:
                return {"status": 400, "message": "Недостаточно игроков или цвета повторяются"}

            # Активация игры
            game.is_active = True
            game.started_at = datetime.utcnow()
            game.game_state.update({
                "state": "active",
                "start_time": datetime.utcnow().isoformat(),
                "grid_size": 10,
                "cells": {}
            })

            self.db.commit()

            return {
                "status": 200,
                "game_id": game.id,
                "start_time": game.started_at.isoformat(),
                "players": [p.split(":") for p in game.game_players]
            }

        except Exception as e:
            logger.error(f"Error starting game {game_id}: {e}")
            self.db.rollback()
            return {"status": 500, "message": "Ошибка сервера"}


class GameManager(BaseGameManager):
    """Управление игровым процессом с учетом UserState"""

    def __init__(self, db: Session, game_id: int):
        super().__init__(db)
        self.game_id = game_id
        self.game = self.db.query(Game).get(self.game_id)
        if not self.game:
            raise ValueError(f"Игра {self.game_id} не найдена")

    def _get_user_state(self, username: str) -> UserState:
        """Получает или создает состояние пользователя в текущей игре"""
        user_state = self.db.query(UserState).join(User).filter(
            UserState.game_id == self.game_id,
            User.username == username
        ).first()

        if user_state:
            return user_state

        user = self.db.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError(f"Пользователь {username} не найден")

        # Находим цвет игрока в этой игре
        player_color = None
        for player_entry in self.game.game_players:
            player, color = player_entry.split(":")
            if player == username:
                player_color = color
                break

        if not player_color:
            raise ValueError(f"Пользователь {username} не участник игры")

        user_state = UserState(
            game_id=self.game_id,
            user_id=user.id,
            color=player_color,
            total_clicks=0,
            success_clicks=0,
            failed_clicks=0,
            joined_at=datetime.utcnow()
        )

        self.db.add(user_state)
        self.db.commit()
        return user_state

    def init_data(self) -> Dict:
        """Инициализация данных игры"""
        data = []
        for player_entry in self.game.game_players:
            player, color = player_entry.split(":")
            try:
                player_state = self._get_user_state(player)
                data.append({
                    "username": player,
                    "color": color,
                    "total_clicks": player_state.total_clicks,
                    "success_clicks": player_state.success_clicks,
                    "failed_clicks": player_state.failed_clicks
                })
            except ValueError as e:
                logger.warning(f"Ошибка получения состояния игрока {player}: {e}")

        return {
            "status": 200,
            "players": data,
            "game_state": self.game.game_state,
            "total_clicks": self.game.total_clicks,
            "clicked_cells_count": len(self.game.clicked_cells)
        }

    async def register_click(self, username: str, coord: int) -> Dict:
        """Регистрирует клик игрока"""
        try:
            if not self.game.is_active:
                return {"status": 400, "error": "Игра не активна"}

            if not isinstance(coord, int) or coord < 1 or coord > 100:
                return {"status": 400, "error": "Некорректные координаты"}

            user_state = self._get_user_state(username)
            is_success = coord not in self.game.clicked_cells

            # Обновляем статистику
            self.game.total_clicks += 1
            user_state.user.total_clicks += 1
            user_state.total_clicks += 1

            if is_success:
                self.game.clicked_cells.append(coord)
                self.game.game_state.setdefault("cells", {})[str(coord)] = user_state.color
                user_state.user.success_clicks += 1
                user_state.success_clicks += 1
            else:
                user_state.user.failed_clicks += 1
                user_state.failed_clicks += 1

            self.db.commit()

            return {
                "status": 200,
                'click': 1 if is_success else 0,
                "player": username,
                "coord": coord,
                "color": user_state.color if is_success else None,
                "is_success": is_success,
                "state": self.game.game_state,
                "game_stats": {
                    "total_clicks": self.game.total_clicks,
                    "clicked_cells": len(self.game.clicked_cells)
                }
            }

        except Exception as e:
            logger.error(f"Ошибка регистрации клика: {e}")
            self.db.rollback()
            return {"status": 500, "error": str(e)}

    async def check_finish_game(self) -> Optional[Dict]:
        """Проверяет завершение игры"""
        if len(self.game.clicked_cells) >= 100:
            return await self.finish_game()
        return None

    async def finish_game(self) -> Dict:
        """Завершает игру и возвращает результаты"""
        try:
            if not self.game.is_active:
                return {"status": 400, "error": "Игра уже завершена"}

            players_stats = []
            for player_entry in self.game.game_players:
                username, color = player_entry.split(":")
                user_state = self._get_user_state(username)

                stats = {
                    "username": username,
                    "color": color,
                    "score": user_state.success_clicks,
                    "stats": {
                        "total": user_state.total_clicks,
                        "success": user_state.success_clicks,
                        "failed": user_state.failed_clicks
                    }
                }
                players_stats.append(stats)

                # Обновляем глобальную статистику
                user_state.user.total_games += 1
                if color not in user_state.user.color_used:
                    user_state.user.color_used.append(color)

            # Определяем победителей
            max_score = max(p["score"] for p in players_stats)
            winners = [p["username"] for p in players_stats if p["score"] == max_score]

            # Обновляем статистику победителей
            for user in self.db.query(User).filter(User.username.in_(winners)):
                user.wins_count += 1

            # Финализируем игру
            self.game.is_active = False
            self.game.winners = winners
            self.game.game_state.update({
                "status": "finished",
                "end_time": datetime.utcnow().isoformat(),
                "winners": winners,
                "scores": {p["username"]: p["score"] for p in players_stats}
            })

            self.db.commit()

            return {
                "status": 200,
                "winners": winners,
                "players_stats": players_stats,
                "final_state": self.game.game_state
            }

        except Exception as e:
            logger.error(f"Ошибка завершения игры: {e}")
            self.db.rollback()
            return {"status": 500, "error": str(e)}