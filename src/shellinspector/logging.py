import logging
from functools import cache

from termcolor import colored


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "light_grey",
        logging.INFO: "light_grey",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "red",
    }

    def format(self, record):
        s = super().format(record)
        return colored(s, self.COLORS.get(record.levelno))


@cache
def _get_handler():
    ch = logging.StreamHandler()
    ch.setFormatter(ColorFormatter())
    return ch


def get_logger(name):
    logger = logging.root
    logger.handlers = []
    logger.addHandler(_get_handler())
    return logger
