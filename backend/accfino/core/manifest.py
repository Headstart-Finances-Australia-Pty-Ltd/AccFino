"""Core's contribution to the module registry: the model modules Core owns (identity, organisations, subscription, platform settings, LLM key pool)."""
from accfino.shared.contracts import registry

registry.register_core(models=(
    "accfino.core.models",
    "accfino.core.identity.user", "accfino.core.identity.role", "accfino.core.identity.permission",
    "accfino.core.identity.association", "accfino.core.identity.password_reset_token",
    "accfino.core.subscription.licence", "accfino.core.subscription.pricing_model",
    "accfino.core.platform_setting",
    "accfino.shared.llm.key_pool_model",
))
