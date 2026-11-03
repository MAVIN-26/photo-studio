def format_price_minor(value: int) -> str:
    rubles, kopecks = divmod(value, 100)
    price = f"{rubles:,}".replace(",", " ")
    return f"{price},{kopecks:02d}" if kopecks else price
