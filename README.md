# Игровая платформа

## 🔗 Основные ссылки

- **Профиль игрока**  
  Адрес: http://127.0.0.1:8000/profile

- **Лобби**  
  Адрес: http://127.0.0.1:8000/lobby

- **Игра**  
  Адрес для конкретной игры (например, игра №29): http://127.0.0.1:8000/game/29

---

## 🚀 Установка и запуск

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Запустить сервер:

```bash
uvicorn main:app --reload
```

---

## 📦 Стек технологий

- **FastAPI** — backend-сервер
- **Uvicorn** — сервер для запуска ASGI приложений
- **HTML + CSS** — интерфейс пользователя
- **Jinja2** — шаблонизатор для генерации страниц
- **JavaScript** — реализация логики игры (находится в разработке 🚧)

---

> ⚙ Игра не завершения, логика на стороне клиента (JavaScript) не соврещенна !
