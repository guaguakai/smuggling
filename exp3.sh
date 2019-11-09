FILENAME='1107-stochastic-server'

NODES=30
BUDGET=2
PROB=0.2
CUTSIZE='0.5n'
SELECTION='derivative'

python3 exp3.py --filename=$FILENAME --number-nodes=$NODES --budget=$BUDGET --prob=$PROB --cut-size=$CUTSIZE --block-selection=$SELECTION