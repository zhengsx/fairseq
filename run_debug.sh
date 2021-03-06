#!/usr/bin/env bash

EXEC_ID=debug
DATA_DIR=~/data/wiki_book_32768
TOTAL_UPDATES=1000000
WARMUP_UPDATES=10000
PEAK_LR=0.0001
TOKENS_PER_SAMPLE=512
MAX_POSITIONS=512
MAX_SENTENCES=16 # 32 for v100 and fp16
UPDATE_FREQ=100
SEED=100
LOG_DIR=~/exps/fairseq/SE-F-${EXEC_ID}

echo 'Environment'


echo 'Start Training'
python3 train.py --fp16 ${DATA_DIR} --ddp-backend=no_c10d \
    --task masked_lm --criterion masked_lm --restore-file=/home/tianyuan/models/baseline-15w.pt\
    --arch roberta_base --sample-break-mode complete --tokens-per-sample ${TOKENS_PER_SAMPLE} \
    --optimizer adam --adam-betas '(0.9, 0.98)' --adam-eps 1e-6 --clip-norm 0.0 \
    --lr-scheduler polynomial_decay --lr ${PEAK_LR} --warmup-updates ${WARMUP_UPDATES} --total-num-update ${TOTAL_UPDATES} \
    --dropout 0.1 --attention-dropout 0.1 --activation-dropout 0.1 --weight-decay 0.01 \
    --max-sentences ${MAX_SENTENCES} --update-freq ${UPDATE_FREQ} --seed ${SEED} \
    --encoder-normalize-before  \
    --max-update ${TOTAL_UPDATES} --log-format simple --log-interval 500 --tensorboard-logdir ~/${LOG_DIR} \
    --save-interval-updates 50000 --keep-interval-updates 6 --no-epoch-checkpoints --skip-invalid-size-inputs-valid-test --save-dir ~/exps/fairseq/SE-F-${EXEC_ID}
