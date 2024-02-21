import logging


class Logger:
    def __init__(self, level=logging.INFO):
        name = "stream_external_tools"
        # Create a custom logger with the given name
        self.logger = logging.getLogger(name)
        # Set the logging level
        self.logger.setLevel(level)
        # Create handlers for console and file output
        self.c_handler = logging.StreamHandler()
        self.f_handler = logging.FileHandler(name + ".log")
        # Set the format for the handlers
        self.c_format = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s - %(message)s")
        self.f_format = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s - %(message)s")
        self.c_handler.setFormatter(self.c_format)
        self.f_handler.setFormatter(self.f_format)
        # Add the handlers to the logger
        self.logger.addHandler(self.c_handler)
        self.logger.addHandler(self.f_handler)

    def get_logger(self):
        return self.logger
