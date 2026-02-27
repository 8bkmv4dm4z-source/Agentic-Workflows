# errors.py

class AgentError(Exception):
    """Base class for agent-related errors."""
    pass


# ----- Control Classification -----

class RetryableAgentError(AgentError):
    """Errors that allow retry."""
    pass


class FatalAgentError(AgentError):
    """Errors that should stop execution immediately."""
    pass


# ----- Validation Errors -----

class InvalidJSONError(RetryableAgentError):
    pass


class SchemaValidationError(RetryableAgentError):
    pass


class MissingActionError(RetryableAgentError):
    pass


class UnknownActionError(RetryableAgentError):
    pass


# ----- Tool Errors -----

class ToolExecutionError(RetryableAgentError):
    pass


class UnknownToolError(FatalAgentError):
    pass


# ----- LLM Errors -----

class LLMError(RetryableAgentError):
    pass