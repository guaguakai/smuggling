FILENAME="0903-server"
BUDGET=2
NODES=30
EPOCHS=51
PROB=0.2

echo $VAR
SEED=$VAR
MINCUT=1
METHOD=1
python3 pathProbabilities.py --epochs=$EPOCHS --fixed-graph=0 --method=$METHOD --seed=$SEED --filename=$FILENAME --budget=$BUDGET --distribution=1 --number-nodes=$NODES --number-graphs=1 --number-samples=50 --learning-rate=0.001 --prob=$PROB --feature-size=8 --number-sources=2 --number-targets=2 --mincut=$MINCUT

