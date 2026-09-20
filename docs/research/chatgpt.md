I would add **`options` for Choice, `levels` for Score, and explicit comparisons to turn their outputs into Boolean factors.** Everything else stays as before.

TypeSafe’s own building example combines a topic Choice, several detection Nouls, and a frustration Score. Your format can express the same mixture without introducing a workflow language. ([TypeSafe AI][1])

## 1. Three question shapes, inferred from their contents

| TOML definition                                  | Primitive | Convenient result                  |
| ------------------------------------------------ | --------- | ---------------------------------- |
| A string, or `question` with optional `yes`/`no` | Noul      | `boolean`, using the shared cutoff |
| `question` + `options`                           | Choice    | A typed string literal             |
| `question` + `levels`                            | Score     | A number                           |

These convenience values belong to **your proposed library**; preserve the underlying API answers and probabilities separately. Noul returns the probability of yes, Choice returns a selected option and its distribution, and Score returns a probability-weighted position along ordered levels. ([TypeSafe AI][2])

No redundant `type = "choice"` is necessary. Having both `options` and `levels` would be a compile error.

**The important boundary:** Boolean combinations accept Booleans—not the truthiness of a Choice string or Score number. Converting those requires a named comparison.

## 2. A fuller example: assessing an agent task

This describes **what kind of work you have, its demands, and how well it is specified**. It does not select a model, spawn workers, or perform an action.

The caller supplies `task` and `context` as input state. All syntax below is the proposed library format.

```toml
# ── What kind of work is this? ────────────────────────────────

[work.kind]
question = "What is the primary deliverable requested in `task`?"

[work.kind.options]
implementation = "A change to code or configuration, including a bug fix."
investigation = "An explanation of a cause; a fix is not requested yet."
review = "An assessment of an existing change or artifact."
other = "None of these fits, or the main deliverable is unclear."


# ── What makes the reasoning demanding? ──────────────────────

[reasoning]
symptom_unexplained = """
Does `task` describe behaviour whose cause is not established in `context`?
"""
cause_needed = """
Does fulfilling `task` require establishing the cause of the described behaviour?
"""

diagnosis = { all = ["symptom_unexplained", "cause_needed"] }

subtle_correctness = """
Does `task` require reasoning about concurrency, ordering, or numerical correctness?
"""

demanding = { at_least = 2, of = ["diagnosis", "coupled_design", "subtle_correctness"] }

[reasoning.coupled_design]
question = "Must changes in different components be designed together to fulfil `task`?"
yes = { what = "Their interfaces or behaviour must be decided jointly.", example = "Design both sides of a new streaming protocol." }
no = { what = "Edits can be decided independently.", example = "Apply an identical rename across several components." }


# ── Could useful parts be delegated independently? ───────────

[delegation]
separable = """
Can `task` be split into useful subtasks that do not need each other's unfinished work?
"""
handoff_complete = """
Does `context` contain enough information to specify those subtasks
without reconstructing earlier decisions?
"""

parallel_friendly = { all = ["separable", "handoff_complete"] }


# ── How well specified is the task? ──────────────────────────

[context]
outcome_clear = """
Is the required end result of `task` clear from the supplied information?
"""
constraints_clear = """
Are constraints that would materially change the solution
resolved in `task` or `context`?
"""

requirements_clear = { all = ["outcome_clear", "constraints_clear"] }
missing_requirements = { not = "requirements_clear" }

[context.specificity]
question = { text = "How specifically does `context` describe how to complete `task`?", focus = "Judge the supplied instructions, not task difficulty." }

# Ordered from least to most specific; positions are 0, 1, 2.
levels = [
  "The desired outcome is given, but the target and method need discovery.",
  "The relevant target is identified, but the method still needs choosing.",
  "A specific procedure or directly applicable worked example is supplied.",
]


# ── Higher-level factors; still no actions ───────────────────

[factors]
implementation = { ref = "work.kind", is = "implementation" }

# An explicit numeric comparison, not automatic rounding.
instruction_rich = { ref = "context.specificity", gte = 1.5 }

well_specified_change = { all = ["implementation", "context.requirements_clear", "instruction_rich"] }
parallelizable_change = { all = ["implementation", "delegation.parallel_friendly"] }
reasoning_or_context_gap = { any = ["reasoning.demanding", "context.missing_requirements"] }
```

The important properties are:

**The breakdown preserves voting semantics.** `diagnosis` contains two checks but contributes only **one vote** to `demanding`. Making that concept more detailed does not increase its influence.

**Structure expands only where useful.** Most questions are strings. One has structured yes/no boundaries; another separates the question from its focus. These objects map to structure the API already accepts for instructions and criteria—they do not need additional interpretation rules. ([TypeSafe AI][3])

**Composition does not add model calls.** This file contains eight Nouls, one Choice, and one Score, plus ten locally computed factors. The ten questions can be evaluated together against the same state; combinations are then evaluated locally. The model questions remain independent and cannot see one another’s answers. 

## 3. Only two new comparison forms

### Choice → Boolean: `is`

```toml
implementation = { ref = "work.kind", is = "implementation" }
```

Meaning: **the selected Choice value equals `"implementation"`**.

It is not a probability threshold. The raw distribution remains available to code when uncertainty matters.

The compiler can validate the option name. This should fail immediately:

```toml
implementation = { ref = "work.kind", is = "implementaton" }
```

For several acceptable options, reuse existing combinations rather than add another operator:

```toml
implementation = { ref = "work.kind", is = "implementation" }
investigation = { ref = "work.kind", is = "investigation" }

problem_solving = { any = ["implementation", "investigation"] }
```

### Score → Boolean: `gte`

```toml
instruction_rich = { ref = "context.specificity", gte = 1.5 }
```

Meaning: **the returned numerical Score is at least `1.5`**.

No automatic rounding, inferred category, or confidence adjustment. A three-level Score runs from `0` to `2`, including fractional values; its number is an average over the level probabilities. Different distributions can produce the same average. ([TypeSafe AI][4])

I would initially support just `is` and `gte`. Other comparisons can be added when an actual example needs them—not as a complete expression language upfront.

## 4. Given your threshold experience, Score should be optional—not contagious

The `1.5` above is an **illustrative operating point**, not a recommended or validated threshold.

For your preferred semantic style, replace that definition with a Noul:

```toml
instruction_rich = """
Does `context` supply a specific procedure or directly applicable
worked example for completing `task`?
"""
```

Everything consuming `instruction_rich` stays unchanged.

That gives you a useful distinction:

> **Use Score when the graded value itself is useful. Use Noul when the meaningful output is a semantic condition.**

You could retain `context.specificity` for displaying or comparing tasks while using the Noul in combinations. Those would be separate judgments and could disagree; the library should not pretend one is mathematically derived from the other.

Likewise, **use Choice when one category should win**. Use separate Nouls when multiple properties can apply simultaneously. That distinction is explicit in TypeSafe’s skill guidance. 

I would **not** initially introduce something like:

```toml
instruction_rich = { ref = "context.specificity", at_least = "detailed" }
```

It looks friendly but hides an important question: does that compare the mean, round to a level, select the most probable level, or sum the probability above a boundary? Keeping numerical comparison explicit avoids that ambiguity.

## 5. What code generation gives you

The generated convenience result would preserve the same grouping:

```typescript
values.work.kind;
// "implementation" | "investigation" | "review" | "other"

values.context.specificity;
// number

values.reasoning.diagnosis;
// boolean

values.reasoning.demanding;
// boolean

values.factors.well_specified_change;
// boolean
```

The native answers stay available separately, including Choice/Score distributions and the original Noul probabilities. The SDK already infers native answer types from question definitions; the generator mainly preserves those types from TOML and adds the derived-factor types. ([TypeSafe AI][5])

Keep the earlier reference rules: **bare names are local; dotted names start at the file root**. Validate references, option names, operand types, and cycles. Missing answers remain errors—not `false` values that `not` might accidentally turn into `true`.

**The resulting language is still small: questions produce typed values; comparisons produce Booleans; combinations build larger Boolean concepts. Code decides what those concepts mean operationally.**

[1]: https://docs.typesafe.ai/concepts/how-to-build-with-system-one "How to build with TypeSafe - TypeSafe AI"
[2]: https://docs.typesafe.ai/primitives/noul "Noul - TypeSafe AI"
[3]: https://docs.typesafe.ai/primitives/advanced "Advanced: structure - TypeSafe AI"
[4]: https://docs.typesafe.ai/primitives/score "Score - TypeSafe AI"
[5]: https://docs.typesafe.ai/sdk/javascript "JavaScript SDK - TypeSafe AI"

---
**I would lean into TOML’s dotted keys, subtables, and arrays of tables—not invent more prompt syntax.**

One adjustment to the earlier design: **use `instructions` for the prompt content**, rather than placing `question`, `focus`, and `compare` directly alongside library configuration. TypeSafe already accepts structured instructions and structured criteria, so preserve those objects instead of converting them into prose. ([TypeSafe AI][1])

Then your library only understands this small outer vocabulary:

| Your TOML                         | Compiles to                                  |
| --------------------------------- | -------------------------------------------- |
| `instructions`                    | API `instructions`, unchanged                |
| `options`                         | Choice `criteria`                            |
| `yes` / `no`                      | Noul `criteria.true` / `criteria.false`      |
| `levels`                          | Score `criteria`, preserving array order     |
| `all`, `any`, voting, comparisons | Locally computed factors—not model questions |

Everything inside the instructions and criteria is **prompt data**, not a special library feature.

## 1. Your Choice example becomes this

```toml
[card_help_topic]
instructions.question = "Which disposable virtual card topic is the user asking about?"
instructions.focus = "Classify the information the user wants."

[card_help_topic.options.get_disposable_virtual_card]
what = "Purpose, eligibility, or setup"
not_for = "Quantity, transaction, or merchant restrictions"
examples = [
  "How can I get a disposable virtual card?",
  "What are disposable cards for?",
]

[card_help_topic.options.disposable_card_limits]
what = "Quantity, transaction, or merchant restrictions"
not_for = "Purpose, eligibility, or setup"
examples = [
  "How many disposable cards can I make per day?",
  "Where can I use a disposable card?",
]
```

Presence of `options` means Choice. Its keys become the possible returned labels, matching the API’s option-map structure. ([TypeSafe AI][2])

**No need to define `what`, `not_for`, or `examples` in your library’s schema.** Tomorrow you could add `edge_cases`, `terminology`, or a nested taxonomy, and the compiler would simply preserve that content.

The distinction is: **validate the configuration envelope strictly; leave the prompt’s internal vocabulary open.**

## 2. Nouls: dotted keys keep a rich question together

Your credential check can stay in one table:

```toml
[spam.requests_credentials]
instructions.question = "Does the message request a sensitive credential?"
instructions.compare = ["`ticket.message`", "`policy.sensitive_credentials`"]
instructions.focus = "Look for a request to disclose the credential itself."

yes.what = "Asks the recipient to disclose a listed credential"
yes.examples = ["Reply with your password", "Send us your API key"]

no.what = "Does not ask the recipient to disclose a credential"
no.examples = ["Use this link to reset your password"]
```

Here `yes.what` and `yes.examples` are simply two fields of one nested object. **That nesting is already provided by TOML**, rather than something your compiler must invent. ([toml.io][3])

Your compiler maps `yes` and `no` to the optional true/false criteria supported by Noul. ([TypeSafe AI][4])

For simpler questions, retain the shorthand:

```toml
[spam]
unexpected_reward = """
Does `ticket.message` announce an unsolicited prize, payment, or reward,
excluding an expected refund or payroll deposit?
"""
```

That is an **alternative definition** of `spam.unexpected_reward`, not something to declare alongside an expanded definition of the same question.

Importantly, `instructions.compare` is still guidance to the model. **It does not automatically fetch those fields or restrict the supplied context.** State preparation remains explicit in your application.

## 3. Scores: use TOML’s ordered array of tables

```toml
[frustration]
instructions.question = "How frustrated does the customer appear?"
instructions.inspect = "`ticket.message`"
instructions.focus = "Judge expressed frustration, not issue severity."

[[frustration.levels]]
what = "Calm and matter-of-fact"
signals = ["Neutral wording", "No complaint about the experience"]

[[frustration.levels]]
what = "Frustrated but civil"
signals = ["Expresses annoyance", "Remains constructive"]

[[frustration.levels]]
what = "Very angry or threatening to leave"
signals = ["Hostile language", "Threatens cancellation or churn"]
```

`[[...]]` appends an object to an array, preserving encounter order. That is exactly the shape needed for structured Score levels. ([toml.io][3])

These three positions correspond to `0`, `1`, and `2`; the returned Score can be fractional because it is a probability-weighted average of the positions. **Do not infer the order from a map of named levels.** ([TypeSafe AI][5])

For simpler descriptions, the same underlying shape can be written compactly:

```toml
[frustration]
instructions = "How frustrated does the customer appear?"
levels = ["Calm and matter-of-fact", "Frustrated but civil", "Very angry"]
```

Again: alternative representations, not additional definitions.

## 4. The full triage example needs explicit answer-field references

Your Python example reveals why returning only Boolean conveniences would be too restrictive: **sometimes you need the Noul probability, sometimes a selected Choice, sometimes a Score, and sometimes confidence.**

I would allow references to the native answer fields:

```text
spam.requests_credentials.noul   → probability of yes
topic.choice                    → selected option
topic.confidence                → Choice confidence
frustration.score               → numeric Score
frustration.confidence          → Score confidence
```

These correspond to the API’s actual outputs. Noul does **not** have a separate confidence field. ([TypeSafe AI][4])

### Weighted combination: one additional operation

Your weighted spam calculation fits a plain table:

```toml
[spam.risk.weighted_sum]
"spam.requests_credentials.noul" = 0.45
"spam.sender_identity_mismatch.noul" = 0.30
"spam.unexpected_reward.noul" = 0.25
```

The quoted keys are complete reference strings. The compiler evaluates:

```text
spam.risk = sum(reference_value × weight)
```

**No automatic normalization, Boolean conversion, or invented confidence.** It is a locally computed number, not another model Score question—and not automatically a calibrated probability of spam.

### Voting remains a different, equally simple operation

```toml
[spam.corroborated]
at_least = 2
of = ["requests_credentials", "sender_identity_mismatch", "unexpected_reward"]
```

This counts Boolean results using the library’s shared Noul cutoff—for example, `p(true) > 0.5`.

The difference is visible in the configuration:

> **Voting counts passed criteria. A weighted sum combines numerical evidence. They are not equivalent.**

### Comparisons then produce the factors your code consumes

```toml
[factors]
risk_in_gray_band = { ref = "spam.risk", gt = 0.4, lt = 0.6 }
topic_uncertain = { ref = "topic.confidence", lt = 0.75 }

review_signal = { any = ["risk_in_gray_band", "topic_uncertain"] }
spam_threshold_reached = { ref = "spam.risk", gte = 0.6 }

billing_topic = { ref = "topic.choice", is = "billing" }
orders_topic = { ref = "topic.choice", is = "orders" }

refund_requested = { ref = "billing.refund_requested.noul", gte = 0.7 }
mentions_open_order = { ref = "orders.mentions_open_order.noul", gte = 0.7 }

frustration_high = { ref = "frustration.score", gte = 1.5 }
frustration_confident = { ref = "frustration.confidence", gte = 0.7 }

high_priority_signal = { all = ["frustration_high", "frustration_confident"] }
```

Only a few rules are needed:

**Multiple comparisons on one reference are ANDed.** Thus `gt = 0.4, lt = 0.6` reproduces the strict bounds in your example without adding a separate interval operator.

**Bare references remain local; dotted references start at the file root.** That preserves the grouping convention we already established.

**Answer fields are type-checked.** `topic.noul`, `frustration.choice`, or a misspelled Choice label should fail before an API call. Derived factors do not magically acquire `.confidence`.

The numbers above reproduce your example, not recommended defaults. Also, the API’s Choice/Score confidence describes the returned distribution; it is not a measured application success rate. ([TypeSafe AI][6])

## 5. Where I would stop

The TOML contains **questions, rubrics, and derived factors**. Your Python still handles the closed-ticket check, constructs the relevant state, and determines what to do with the factors.

In particular, `review_signal` and `spam_threshold_reached` can both be true. **The code retains the ordering that gives review precedence.** No hidden routing behaviour is attached to either factor.

I put all seven questions from your triage example, their structured criteria, and these combinations into a [complete proposed `triage.toml`](sandbox:/mnt/data/triage.toml). It parses as TOML and its references resolve; it is a proposed library format, not something the native SDK loads directly.

**The useful abstraction is small: TOML supplies the structure; the compiler handles types and references; JeV interprets the prompt content; code owns the consequences.**

[1]: https://docs.typesafe.ai/primitives/advanced "Advanced: structure - TypeSafe AI"
[2]: https://docs.typesafe.ai/primitives/choice "Choice - TypeSafe AI"
[3]: https://toml.io/en/v1.0.0 "TOML: English v1.0.0"
[4]: https://docs.typesafe.ai/primitives/noul "Noul - TypeSafe AI"
[5]: https://docs.typesafe.ai/primitives/score "Score - TypeSafe AI"
[6]: https://docs.typesafe.ai/confidence "Confidence - TypeSafe AI"
