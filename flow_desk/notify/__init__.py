"""flow_desk/notify: one sender, one environment variable, no stored URL."""
from .sender import ENV_VAR, deliver, should_push

__all__ = ["ENV_VAR", "deliver", "should_push"]
