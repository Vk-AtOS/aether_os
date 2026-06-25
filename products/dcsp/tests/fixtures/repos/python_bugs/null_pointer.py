def get_user_email(user_dict):
    return user_dict["profile"]["email"].lower()

def process_users(users):
    emails = []
    for user in users:
        email = get_user_email(user)
        emails.append(email)
    return emails
