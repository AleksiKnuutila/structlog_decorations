import collections
import logging
import logging.config
import structlog
from common import config
from typing import Callable
import uuid


def _order_keys(logger, method_name, event_dict):
    return collections.OrderedDict(
        sorted(event_dict.items(), key=lambda item: (item[0] != "event", item))
    )


def configure_logger(
    log_to_console=True, color_console=True, log_to_file=True, filename=None
):
    pre_chain = []

    if structlog.contextvars:
        pre_chain += [
            structlog.contextvars.merge_contextvars,
        ]

    pre_chain += [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _order_keys,
    ]

    structlog.configure_once(
        processors=pre_chain
        + [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handlers = {}
    if log_to_console:
        handlers["console"] = {"()": logging.StreamHandler, "formatter": "console"}
    if log_to_file and filename:
        handlers["file"] = {
            "()": logging.handlers.RotatingFileHandler,
            "filename": filename,
            "formatter": "json",
            "maxBytes": 25000000,
            "backupCount": 100,
        }

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=color_console),
                "foreign_pre_chain": pre_chain,
            },
            "json": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.processors.JSONRenderer(),
                "foreign_pre_chain": pre_chain,
            },
        },
        "handlers": handlers,
        "loggers": {
            "": {"propagate": True, "handlers": list(handlers.keys()), "level": "DEBUG"}
        },
    }
    logging.config.dictConfig(logging_config)


def get_logger(filename):
    # Rotate logfile before starting new logger
    temporary_handler = logging.handlers.RotatingFileHandler(
        filename=filename, backupCount=50
    )
    temporary_handler.doRollover()

    configure_logger(filename=filename)
    return structlog.get_logger()


def set_trace_id(function: Callable, trace_id: str) -> None:
    global_var = function.__globals__
    global_var["trace_id"] = trace_id


def log_function_calls(original_function):
    trace_id = str(uuid.uuid4())
    set_trace_id(original_function, trace_id)
    function_name = f"{original_function.__module__}.{original_function.__name__}"
    logger = custom_logger.bind(function_name=function_name, trace_id=trace_id)

    def new_function(*args, **kwargs):
        log_args=dict(kwargs)
        for key in log_args.keys():
            if hasattr(log_args[key], '__len__') and len(log_args[key]) > 5:
                size=len(log_args[key])
                log_args[key] = f'An object of size {size}'
        logger.info("Function called", args=args, kwargs=log_args)
        try:
            result = original_function(*args, **kwargs)
        except Exception as e:
            logger.warning("Exception raised", error=str(e))
            raise e
        logger.info("Function returned", result=result)

        return result

    return new_function


def log_class_methods(Cls):
    class NewCls:
        def __init__(self, *args, **kwargs):
            custom_logger.info("__init__ called", class_name=Cls.__name__, args=args, kwargs=kwargs)
            self.oInstance = Cls(*args, **kwargs)
            custom_logger.info("__init__ finished ", class_name=Cls.__name__, args=args, kwargs=kwargs)

        def __getattribute__(self, s):
            """
            this is called whenever any attribute of a NewCls object is accessed. This function first tries to
            get the attribute off NewCls. If it fails then it tries to fetch the attribute from self.oInstance (an
            instance of the decorated class). If it manages to fetch the attribute from self.oInstance, and
            the attribute is an instance method then `time_this` is applied.
            """
            try:
                x = super(NewCls, self).__getattribute__(s)
            except AttributeError:
                pass
            else:
                return x
            x = self.oInstance.__getattribute__(s)
            if type(x) == type(self.__init__):  # an instance method
                return log_function_calls(x)
            else:
                return x

    return NewCls


custom_logger = get_logger(config["log_file"])
