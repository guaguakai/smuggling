FILENAME='1009-2300-server'

NODES=20
NOISE=0.1
BUDGET=2
PROB=0.2

python3 generate_fig4.py --filename=$FILENAME --number-nodes=$NODES --noise=$NOISE --budget=$BUDGET --prob=$PROB
