# Mission Rubric (Compact)

Use this rubric when classifying mission outcomes from `lastRun.txt`.

## Task 1: Text Analysis Pipeline
- Expected tools: `text_analysis`, `string_ops`, `write_file`
- Expected artifact: `analysis_results.txt`

## Task 2: Data Analysis and Sorting
- Expected tools: `data_analysis`, `sort_array`, `math_stats`
- Expected behavior: non-outlier analysis, sorting, mean/sum usage consistency

## Task 3: JSON Processing
- Expected tools: `json_parser`, `regex_matcher`, `sort_array`, `write_file`
- Expected artifact: `users_sorted.txt` with names in stable alphabetical order

## Task 4: Pattern Matching and Transform
- Expected tools: `regex_matcher`, `math_stats`, `write_file`
- Expected artifact: `pattern_report.txt` containing extracted numbers + sum + mean

## Task 5: Fibonacci with Analysis
- Expected tools: `write_file` (+ optional `memoize` depending on policy), optional `repeat_message`
- Expected artifact: `fib50.txt` with valid Fibonacci CSV and required count per mission contract

## Classification Rules
- `PASS`: tool chain and artifact content satisfy contract
- `WARN`: partial success, ambiguous attribution, or non-blocking mismatch
- `FAIL`: contract broken, wrong/missing outputs, or invalid finish claims
