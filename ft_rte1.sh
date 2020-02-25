TOTAL_NUM_UPDATES=2036  # 10 epochs through RTE for bsz 16
WARMUP_UPDATES=122     # 6 percent of the number of updates
LR=2e-05                # Peak LR for polynomial LR scheduler.
NUM_CLASSES=2
MAX_SENTENCES=16        # Batch size.
ROBERTA_PATH=/home/tianyuan/exps/fairseq/baseline-robert-base-32768-p512-t128-b256/checkpoint_1_100000.pt
SEED=101

CUDA_VISIBLE_DEVICES=1 python3 train.py ~/data/glue-32768-fast/RTE-bin/ \
    --restore-file $ROBERTA_PATH \
    --max-positions 128 --skip-invalid-size-inputs-valid-test \
    --max-sentences $MAX_SENTENCES \
    --max-tokens 4400 \
    --task sentence_prediction \
    --reset-optimizer --reset-dataloader --reset-meters \
    --required-batch-size-multiple 1 \
    --init-token 0 --separator-token 2 \
    --arch roberta \
    --criterion sentence_prediction \
    --num-classes $NUM_CLASSES \
    --dropout 0.1 --attention-dropout 0.1 \
    --weight-decay 0.1 --optimizer adam --adam-betas "(0.9, 0.98)" --adam-eps 1e-06 \
    --clip-norm 0.0 \
    --lr-scheduler polynomial_decay --lr $LR --total-num-update $TOTAL_NUM_UPDATES --warmup-updates $WARMUP_UPDATES \
    --max-epoch 10 \
    --find-unused-parameters --seed $SEED \
    --best-checkpoint-metric accuracy --maximize-best-checkpoint-metric;
