"""Model-promotion application errors."""


class ModelPromotionError(Exception):
    """Base error for controlled model promotion."""


class PromotionValidationError(ModelPromotionError):
    """Raised when a promotion request violates its contract."""


class PromotionNotFoundError(ModelPromotionError):
    """Raised when promotion evidence cannot be found."""


class PromotionPolicyRejectedError(ModelPromotionError):
    """Raised when policy blocks a non-forced promotion."""


class PromotionPreconditionError(ModelPromotionError):
    """Raised when a valid request lacks required promotion evidence or state."""


class PromotionAuthorizationError(ModelPromotionError):
    """Raised when a role cannot perform the requested governance action."""


class PromotionAliasVerificationError(ModelPromotionError):
    """Raised when registry read-back does not confirm the alias mutation."""


class PromotionAuditFinalizationError(ModelPromotionError):
    """Raised after alias mutation when its pending audit cannot be finalized."""
