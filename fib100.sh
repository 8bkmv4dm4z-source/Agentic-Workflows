#!/bin/bash
python3 -c "
a, b = 0, 1
for _ in range(100):
    a, b = b, a + b
print(b)
" > fib100.txt