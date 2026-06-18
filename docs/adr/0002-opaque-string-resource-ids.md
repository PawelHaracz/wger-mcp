# All resource IDs are opaque strings

**Status:** accepted (2026-06-18)

wger 2.6 changed several model IDs from integer to string (UUID) — so clients
can generate IDs locally — affecting `measurement-category`, `measurement`,
`nutritionplan` (+info), `meal`, `mealitem`, `nutritiondiary`, `workoutsession`
and `workoutlog`. Rather than tracking which endpoints are int vs UUID, we treat
**every** wger resource ID as an opaque string across all MCP tools (including
ones wger still serves as int, e.g. `exercise`, `ingredient`), and never do
arithmetic or numeric sorting on IDs.

This is a larger diff and makes some still-numeric IDs surface as strings, but it
future-proofs the tools against further such migrations and keeps the tool API
uniform. Note this extends to foreign keys carried in request/response bodies
(e.g. `plan`, `meal`): values are passed through verbatim, never coerced.
