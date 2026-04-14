from telegram.ext import Application
from config import TOKEN
from db import init_db
from handlers import setup

def main():
    if not TOKEN:
        raise ValueError("NO TOKEN")

    init_db()

    app=Application.builder().token(TOKEN).build()
    setup(app)

    print("BOT RUN")
    app.run_polling()

if __name__=="__main__":
    main()
