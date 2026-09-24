from database import select_rows


def summarize_database(game_date):
    df = select_rows("games", filters=[("GAME_DATE", "eq", game_date)], order_by="GAME_ID")
    return df.describe()
