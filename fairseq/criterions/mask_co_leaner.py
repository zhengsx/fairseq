# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import math
import numpy as np

import torch
import torch.nn.functional as F

from fairseq import metrics, utils
from fairseq.criterions import FairseqCriterion, register_criterion


@register_criterion('mask_co_leaner')
class MaskLeanerCoLoss(FairseqCriterion):
    """
    Implementation for the loss used in masked language model (MLM) training.
    """

    def __init__(self, args, task):
        super(MaskLeanerCoLoss, self).__init__(args, task)

        self.vocab = self.task.source_dictionary
        self.mask_idx = self.task.mask_idx
        self.mask_prob = self.task.args.mask_prob
        self.leave_unmasked_prob = self.task.args.leave_unmasked_prob
        self.random_token_prob = self.task.args.random_token_prob
        self.rand_or_unmask_prob = self.random_token_prob + self.leave_unmasked_prob

        self.mask_whole_words = self.task.args.mask_whole_words
        self.freq_weighted_replacement = self.task.args.freq_weighted_replacement

        self.masker_lambda = args.masker_lambda
        self.do_deterministic = args.masker_deterministic
        if self.random_token_prob > 0.0:
            if self.freq_weighted_replacement:
                weights = np.array(self.vocab.count)
            else:
                weights = np.ones(len(self.vocab))
            weights[:self.vocab.nspecial] = 0
            self.weights = weights / weights.sum()

        self.register_buffer('random_weights', torch.tensor(self.weights).type(torch.float32))

    @staticmethod
    def add_args(parser):
        """Add criterion-specific arguments to the parser."""
        super(MaskLeanerCoLoss,
              MaskLeanerCoLoss).add_args(parser)

        parser.add_argument('--masker_lambda', default=0.5, type=float, metavar='D',
                            help='weight for the deeply supervised loss')
        parser.add_argument('--masker_deterministic', default=False,
                            action='store_true',
                            help='is the mask generated by sampling?')

    def forward(self, model, sample, reduce=True):
        """Compute the loss for the given sample.

        Returns a tuple with three elements:
        1) the loss
        2) the sample size, which is used as the denominator for the gradient
        3) logging outputs to display while training
        """
        # compute MLM loss
        # model.learner model.lm
        raw_inps = sample["net_input"]["src_tokens"]
        raw_targets = sample['target']
        raw_masked_tokens = raw_targets.ne(self.padding_idx)
        inps = raw_targets * raw_masked_tokens + \
               raw_inps * (raw_masked_tokens ^ True)
        sz = inps.size(-1) # all batches should be the same length
        num_mask = int(sz * 0.15)

        masker_out = model.masker(inps)[0]#.view(inps.size(0), -1)
        with torch.no_grad():
            adz = torch.ones_like(masker_out) * 1e-5
            log_masking_softmax = torch.log(masker_out + adz)
            p_logp = log_masking_softmax * masker_out

            masker_entropy = torch.sum(p_logp) * -1.0

            token_length = masker_out.size(1)

            index5 = 5 if token_length > 4 else token_length
            index2 = 2 if token_length > 2 else token_length

            top5_masker, _ = torch.topk(masker_out, index5, dim=-1)
            top2_dist = top5_masker[:, 0] - top5_masker[:, index2-1]
            top5_dist = top5_masker[:, 0] - top5_masker[:, index5-1]
            top2_dist = torch.mean(top2_dist)
            top5_dist = torch.mean(top5_dist)

            #print(masker_entropy, inps.shape)

        #print('masker 1 shape', masker_out.shape)

        if num_mask == 0:
            num_mask = 1
        if self.do_deterministic:
            masked_tokens, masked_idxes = torch.topk(masker_out,
                                                     num_mask, dim=-1)
        else:
            with torch.no_grad():
                #t_masker_out = torch.clamp(masker_out * float(num_mask), 0, 1)
                #random_s = torch.bernoulli(t_masker_out).type(torch.bool)
                #masked_idxes = random_s  # not not index, but table of True of False##

                masked_idxes = torch.multinomial(masker_out, num_mask, replacement=False)


        labels_list = []
        with torch.no_grad():

            #labels = torch.full_like(inps, self.padding_idx)
            #labels[masked_idxes] = inps[masked_idxes]


            rand_or_unmask_prob = self.random_token_prob + self.leave_unmasked_prob

            new_inps = []

            #import IPython
            #IPython.embed()

            for i in range(inps.size(0)):
                inp = inps[i]
                mask = torch.full_like(inp, False).type(torch.bool)
                mask[masked_idxes[i]] = True

                label = torch.full_like(inp, self.padding_idx)
                label[masked_idxes[i]] = inp[masked_idxes[i]]
                labels_list.append(label)

                #import IPython
                #IPython.embed()

                if rand_or_unmask_prob > 0.0:
                    tmp_rand = torch.rand_like(inp.type(torch.float))
                    tmp_rand = (tmp_rand < rand_or_unmask_prob)
                    #tmp_rand = tmp_rand.to(inp.device)
                    #tmp_rand = (torch.rand(sz) < rand_or_unmask_prob).to(mask.device)
                    tmp_rand = tmp_rand.type(mask.type())
                    rand_or_unmask = mask & tmp_rand
                    if self.random_token_prob == 0.0:
                        unmask = rand_or_unmask
                        rand_mask = None
                    elif self.leave_unmasked_prob == 0.0:
                        unmask = None
                        rand_mask = rand_or_unmask
                    else:
                        unmask_prob = self.leave_unmasked_prob / rand_or_unmask_prob
                        decision = torch.rand_like(inp.type(torch.float))  < unmask_prob
                        decision = decision.type(mask.type())
                        unmask = rand_or_unmask & decision
                        rand_mask = rand_or_unmask & (~decision)
                else:
                    unmask = rand_mask = None

                if unmask is not None:
                    mask = mask ^ unmask

                #if self.mask_whole_words is not None:
                #    #mask = torch.repeat(mask, word_lens)
                #    mask = mask.repeat(word_lens)



                new_item = inp.clone()
                #print('mask, new item', mask.shape, new_item.shape, mask.type(), torch.sum(mask).item())
                mask_idxs = torch.full_like(new_item, self.mask_idx)
                new_item = torch.where(mask, mask_idxs, new_item)
                #new_item[mask] = self.mask_idx
                if rand_mask is not None:
                    num_rand_int = rand_mask.sum().item()
                    num_rand = rand_mask.sum()

                    #print('num_rand', num_rand_int)
                    if num_rand_int > 0:
                        #if self.mask_whole_words is not None:
                        #    #rand_mask = torch.repeat(rand_mask, word_lens)
                        #    rand_mask = rand_mask.repeat(word_lens)
                        #    num_rand = rand_mask.sum()
                        #import IPython
                        #IPython.embed()
                        # rand_tensor = torch.tensor(
                        #     np.random.choice(len(self.vocab),
                        #                      num_rand.cpu().numpy(),
                        #                      p=self.weights)).to(mask.device)
                        rand_tensor = torch.multinomial(self.random_weights, num_rand,  False)
                        rand_tensor.type(inps.type())
                        new_item[rand_mask] = rand_tensor
                new_inps.append(new_item)

            new_inp = torch.stack(new_inps, dim=0)
            labels = torch.stack(labels_list, dim=0)

            sample['target'] = labels
            sample['net_input']["src_tokens"] = new_inp
        masked_tokens = sample['target'].ne(self.padding_idx)
        sample_size = masked_tokens.int().sum().item()

        # (Rare case) When all tokens are masked, the model results in empty
        # tensor and gives CUDA error.
        if sample_size == 0:
            masked_tokens = None

        logits = model(**sample['net_input'], masked_tokens=masked_tokens)[0]
        targets = model.get_targets(sample, [logits])

        if sample_size != 0:
            targets = targets[masked_tokens]

        loss = F.nll_loss(
            F.log_softmax(
                logits.view(-1, logits.size(-1)),
                dim=-1,
                dtype=torch.float32,
            ),
            targets.view(-1),
            reduction='sum',
            ignore_index=self.padding_idx,
        )

        #import IPython
        #IPython.embed()

        pred_softmax = F.softmax(logits, dim=-1)

        target_index = targets.unsqueeze(dim=-1)

        #import IPython
        #IPython.embed()
        #print(pred_softmax.shape, targets.shape)
        target_score = torch.gather(pred_softmax, dim=-1, index=target_index)
        target_score = target_score.view(-1)

        masker_out = masker_out[masked_tokens]
        masker_out = masker_out.view(-1)


        target_score = target_score.detach() # important
        target_score = target_score - target_score.mean()
        masker_loss = target_score * masker_out
        masker_loss = masker_loss.sum()

        total_loss = masker_loss * self.masker_lambda + loss
        #print('sample size', sample_size)



        logging_output = {
            'loss': utils.item(loss.data) if reduce else loss.data,
            'ntokens': sample['ntokens'],
            'nsentences': sample['nsentences'],
            'sample_size': sample_size,
            'masker_loss':utils.item(masker_loss.data) if reduce else masker_loss.data,
            'total_loss': utils.item(total_loss.data) if reduce else total_loss.data,
            'masker_entropy': utils.item(masker_entropy.data) if reduce else masker_entropy.data,
            'top2_dist': utils.item(top2_dist.data) if reduce else top2_dist.data,
            'top5_dist': utils.item(top5_dist.data) if reduce else top5_dist.data,
        }
        return total_loss, sample_size, logging_output

    @staticmethod
    def reduce_metrics(logging_outputs) -> None:
        """Aggregate logging outputs from data parallel training."""
        loss_sum = sum(log.get('loss', 0) for log in logging_outputs)
        masker_loss_sum = sum(log.get('masker_loss', 0) for log in logging_outputs)
        total_loss_sum = sum(log.get('total_loss', 0) for log in logging_outputs)
        masker_entropy = sum(log.get('masker_entropy', 0) for log in logging_outputs)
        top2_dist = sum(log.get('top2_dist', 0) for log in logging_outputs) / len(logging_outputs)
        top5_dist = sum(log.get('top5_dist', 0) for log in logging_outputs) / len(logging_outputs)

        sample_size = sum(log.get('sample_size', 0) for log in logging_outputs)

        metrics.log_scalar('loss', loss_sum / sample_size / math.log(2), sample_size, round=3)
        metrics.log_scalar('masker_entropy', masker_entropy / sample_size / math.log(2) , sample_size, round=3)

        metrics.log_scalar('top2_dist', top2_dist, sample_size, round=5)
        metrics.log_scalar('top5_dist', top5_dist, sample_size, round=5)
        metrics.log_scalar('masker_loss', masker_loss_sum / sample_size / math.log(2)  , sample_size, round=5)
        metrics.log_scalar('total_loss', total_loss_sum / sample_size / math.log(2), sample_size, round=3)
        metrics.log_derived('ppl', lambda meters: round(2**meters['loss'].avg, 3))

    @staticmethod
    def logging_outputs_can_be_summed() -> bool:
        """
        Whether the logging outputs returned by `forward` can be summed
        across workers prior to calling `reduce_metrics`. Setting this
        to True will improves distributed training speed.
        """
        return True
