---
name: diotima-statistics
description: Use Diotima's statistical tools correctly (re-check sample planning now; open evidence meter, bounds for unread studies and exploratory meta-analysis later). Use when planning how many claims to re-check by hand or when the user asks how much to trust an aggregate.
---

# Diotima statistics

Available now:

- `plan_recheck_sample(max_error_rate, confidence, max_errors_allowed, planned_sample)`:
  exact Beta(1,1)-Binomial planning of how many claim-passage pairs a human must re-check.
  Example: tolerating at most 1 error with 85% confidence that the true error rate is below
  4% needs at least 83 checked pairs. Report `plan_adequate` and the minimum sample; never
  silently accept an inadequate plan.

Coming in later versions (do not imitate them by hand): the open evidence meter
(Dirichlet-multinomial with visible weights), Manski bounds for studies read only as
abstracts, sensitivity analyses and exploratory random-effects meta-analysis.

Always present a statistic with its inputs, its assumptions and what would change it.
