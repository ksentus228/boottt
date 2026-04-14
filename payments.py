from telegram import LabeledPrice

def premium_invoice(context, chat_id):
    return context.bot.send_invoice(
        chat_id=chat_id,
        title="Премиум 7 дней",
        description="Безлимит 18+ чат",
        payload="premium_7",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("Premium", 180)]
    )
