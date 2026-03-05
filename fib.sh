#!/bin/bash
a=0; b=1; for i in {1..50}; do echo $b; c=$((a+b)); a=$b; b=$c; done
