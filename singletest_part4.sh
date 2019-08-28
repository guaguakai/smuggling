FILENAME="0828-1800-server"
BUDGET=2
NODES=30
EPOCHS=51
PROB=0.3

echo $VAR
SEED=$VAR
MINCUT=1
METHOD=1
python3 pathProbabilities.py --epochs=$EPOCHS --fixed-graph=0 --method=$METHOD --seed=$SEED --filename=$FILENAME --budget=$BUDGET --distribution=1 --number-nodes=$NODES --number-graphs=10 --number-samples=10 --learning-rate=0.0001 --prob=$PROB --feature-size=8 --number-sources=2 --number-targets=2 --mincut=$MINCUT
