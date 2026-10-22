# Tasks

A task is a YAML file in the package library. The id matches `name-001`. The calendar domain is `calendar_email` and its ids are `calendar-001`.

`expected_state` is a partial match. `reference_solution` is replayed by `tasks/validate.py`. A task that the reference cannot reach does not belong in the library.

The library has 25 tasks in each of retail, travel, calendar and email, and banking. Eight are easy, ten are medium, and seven are hard. Seed 17 is the spine every task starts from.
