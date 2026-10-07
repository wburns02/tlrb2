#!/bin/bash
# m3_gt_batch.sh  -- overnight exhibition batch on :97/work2; varied matchups; log-only.
B=~/tlrb2/scripts/m3_gt.sh
$B balcal 600 293 435 293 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
$B nynstl 630 383 460 400 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
$B detmil 630 317 420 340 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
$B sdpit 460 466 630 450 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
$B oakny 425 357 620 317 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
$B houmon 430 433 650 383 >> /mnt/nvme/tlrb2/logs2/gt_batch.log 2>&1
echo BATCH_DONE >> /mnt/nvme/tlrb2/logs2/gt_batch.log
