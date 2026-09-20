# Application-owned data layout

Status: `[data]` is implemented in this package as of 20 September 2026.
Verify support in older installed versions before relying on the generated
`data` export. Applications own the child schema and interpretation.

This example keeps one area's questions, compact metadata, copy and a few
recognition checks together. The `data` namespace is the core feature; every
child name and reference is an application convention.

```toml
title = "Delivery"

[requires]
"message" = "string"

[questions.topic]
type = "choice"
instructions = """
Identify the delivery information requested in `message`.
Asking about a delivery method does not select it.
"""

[questions.topic.criteria]
cost = "Asks about delivery prices or charges."
timing = "Asks when delivery arrives or how long it takes."
none = "No delivery-information request."
unclear = "A delivery question whose meaning is uncertain."

[data]
topics = [
  { id = "cost",   label = "Delivery prices", scope = "delivery_method", reply = "cost" },
  { id = "timing", label = "Delivery times",  scope = "delivery_method", reply = "timing" },
]

templates = [
  { id = "cost",          text = "{method_label} costs {price_label}." },
  { id = "timing",        text = "{method_label}: {timing_label}." },
  { id = "missing_scope", text = "Which delivery method do you mean?" },
]

utterances = [
  { id = "acknowledge", variants = [
    "Of course.",
    "Sure.",
  ] },
  { id = "explain", variants = [
    """
I can explain delivery prices and timing.
The available options depend on your order.
""",
  ] },
]

examples = [
  { message = "what would express set me back?", labels = { topic = "cost" } },
  { message = "how long does standard take?",    labels = { topic = "timing" } },
  { message = "use express",                    labels = { topic = "none" } },
]
```

The application validates IDs, references and placeholders, supplies verified
prices and timing, and decides whether to acknowledge or clarify. systemoneprompts
would preserve data without rendering it, forwarding it to the model or
executing anything. The examples need an application adapter to become CLI
eval cases with full `state` objects; they are not automatically prompt examples.

For a simple dictionary, a keyed table can be shorter than records:

```toml
[data.labels]
cost = "Delivery prices"
timing = "Delivery times"
```

This is an alternative organization, not a requirement to duplicate the labels
from `topics`. Prefer a header for a meaningful collection over a separate
`[data.labels.cost]` header for a single string. Use tables or arrays of tables
when complex records cease to fit comfortably on one row.
