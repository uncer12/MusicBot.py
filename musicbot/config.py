import toml
import logging
import os

EXAMPLE_CONFIG = """\"token\"=\"\" # Токен бота
\"prefix\"=\"!\" # Префикс для команд

[music]
# Опции для музыкальных команд
"max_volume"=250 # Максимальная громкость звука. Установите значение -1 для неограниченной громкости.
"vote_skip"=true # включен ли пропуск голосования
"vote_skip_ratio"=0.5 # минимальное количество голосов, необходимое для пропуска песни
[tips]
"discord_url"="https://discord.gg/PAf9d2KvBT"
"""


def load_config(path="./config.toml"):
    """Загружает конфигурацию из `path`"""
    if os.path.exists(path) and os.path.isfile(path):
        config = toml.load(path)
        return config
    else:
        with open(path, "w") as config:
            config.write(EXAMPLE_CONFIG)
            logging.warn(
                f"Не найден файл конфигурации. Создание файла конфигурации по умолчанию по адресу {path}"
            )
        return load_config(path=path)
