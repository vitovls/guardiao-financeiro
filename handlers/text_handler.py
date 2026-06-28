async def get_message(update, context):
    user = update.message.from_user.first_name
    txt = update.message.text
    
    if txt:
        print(f"[Mensagem Recebida]: {user}: {txt}")