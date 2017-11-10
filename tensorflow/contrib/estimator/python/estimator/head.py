# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Abstractions for the head(s) of a model."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.python.estimator import model_fn
from tensorflow.python.estimator import util
from tensorflow.python.estimator.canned import head as head_lib
from tensorflow.python.estimator.canned import metric_keys
from tensorflow.python.estimator.canned import prediction_keys
from tensorflow.python.estimator.export import export_output
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import lookup_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import metrics as metrics_lib
from tensorflow.python.ops import sparse_ops
from tensorflow.python.ops.losses import losses
from tensorflow.python.saved_model import signature_constants
from tensorflow.python.summary import summary

_DEFAULT_SERVING_KEY = signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY


def multi_class_head(n_classes,
                     weight_column=None,
                     label_vocabulary=None,
                     name=None):
  """Creates a `_Head` for multi class classification.

  Uses `sparse_softmax_cross_entropy` loss.

  This head expects to be fed integer labels specifying the class index.

  Args:
    n_classes: Number of classes, must be greater than 2 (for 2 classes, use
      `binary_classification_head`).
    weight_column: A string or a `_NumericColumn` created by
      `tf.feature_column.numeric_column` defining feature column representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    label_vocabulary: A list of strings represents possible label values. If it
      is not given, that means labels are already encoded as integer within
      [0, n_classes). If given, labels must be string type and have any value in
      `label_vocabulary`. Also there will be errors if vocabulary is not
      provided and labels are string.
    name: name of the head. If provided, summary and metrics keys will be
      suffixed by `"/" + name`. Also used as `name_scope` when creating ops.

  Returns:
    An instance of `_Head` for multi class classification.

  Raises:
    ValueError: if `n_classes`, `metric_class_ids` or `label_keys` is invalid.
  """
  return head_lib._multi_class_head_with_softmax_cross_entropy_loss(  # pylint:disable=protected-access
      n_classes=n_classes,
      weight_column=weight_column,
      label_vocabulary=label_vocabulary,
      name=name)


def binary_classification_head(
    weight_column=None, thresholds=None, label_vocabulary=None, name=None):
  """Creates a `_Head` for single label binary classification.

  This head uses `sigmoid_cross_entropy_with_logits` loss.

  This head expects to be fed float labels of shape `(batch_size, 1)`.

  Args:
    weight_column: A string or a `_NumericColumn` created by
      `tf.feature_column.numeric_column` defining feature column representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    thresholds: Iterable of floats in the range `(0, 1)`. For binary
      classification metrics such as precision and recall, an eval metric is
      generated for each threshold value. This threshold is applied to the
      logistic values to determine the binary classification (i.e., above the
      threshold is `true`, below is `false`.
    label_vocabulary: A list of strings represents possible label values. If it
      is not given, that means labels are already encoded within [0, 1]. If
      given, labels must be string type and have any value in
      `label_vocabulary`. Also there will be errors if vocabulary is not
      provided and labels are string.
    name: name of the head. If provided, summary and metrics keys will be
      suffixed by `"/" + name`. Also used as `name_scope` when creating ops.

  Returns:
    An instance of `_Head` for binary classification.

  Raises:
    ValueError: if `thresholds` contains a value outside of `(0, 1)`.
  """
  return head_lib._binary_logistic_head_with_sigmoid_cross_entropy_loss(  # pylint:disable=protected-access
      weight_column=weight_column,
      thresholds=thresholds,
      label_vocabulary=label_vocabulary,
      name=name)


def regression_head(weight_column=None,
                    label_dimension=1,
                    name=None):
  """Creates a `_Head` for regression using the mean squared loss.

  Uses `mean_squared_error` loss.

  Args:
    weight_column: A string or a `_NumericColumn` created by
      `tf.feature_column.numeric_column` defining feature column representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.
    label_dimension: Number of regression labels per example. This is the size
      of the last dimension of the labels `Tensor` (typically, this has shape
      `[batch_size, label_dimension]`).
    name: name of the head. If provided, summary and metrics keys will be
      suffixed by `"/" + name`. Also used as `name_scope` when creating ops.

  Returns:
    An instance of `_Head` for linear regression.
  """
  return head_lib._regression_head_with_mean_squared_error_loss(  # pylint:disable=protected-access
      weight_column=weight_column,
      label_dimension=label_dimension,
      name=name)


def multi_label_head(n_classes,
                     weight_column=None,
                     thresholds=None,
                     label_vocabulary=None,
                     loss_fn=None,
                     name=None):
  """Creates a `_Head` for multi-label classification.

  Multi-label classification handles the case where each example may have zero
  or more associated labels, from a discrete set. This is distinct from
  `multi_class_head` which has exactly one label per example.

  Uses `sigmoid_cross_entropy` loss averaged over classes. Expects labels as a
  multi-hot tensor of shape `[batch_size, n_classes]`, or as an integer
  `SparseTensor` of class indices.

  Also supports custom `loss_fn`. `loss_fn` takes `(labels, logits)` or
  `(labels, logits, features)` as arguments and returns unreduced loss with
  shape `[batch_size, 1]`. `loss_fn` must support indicator `labels` with shape
  `[batch_size, n_classes]`. Namely, the head applies `label_vocabulary` to the
  input labels before passing them to `loss_fn`.

  Args:
    n_classes: Number of classes, must be greater than 1 (for 1 class, use
      `binary_classification_head`).
    weight_column: A string or a `_NumericColumn` created by
      `tf.feature_column.numeric_column` defining feature column representing
      weights. It is used to down weight or boost examples during training. It
      will be multiplied by the loss of the example.  Per-class weighting is
      not supported.
    thresholds: Iterable of floats in the range `(0, 1)`. Accuracy, precision
      and recall metrics are evaluated for each threshold value. The threshold
      is applied to the predicted probabilities, i.e. above the threshold is
      `true`, below is `false`.
    label_vocabulary: A list of strings represents possible label values. If it
      is not given, that means labels are already encoded as integer within
      [0, n_classes) or multi-hot Tensor. If given, labels must be SparseTensor
      string type and have any value in `label_vocabulary`. Also there will be
      errors if vocabulary is not provided and labels are string.
    loss_fn: Optional loss function.
    name: name of the head. If provided, summary and metrics keys will be
      suffixed by `"/" + name`. Also used as `name_scope` when creating ops.

  Returns:
    An instance of `_Head` for multi-label classification.

  Raises:
    ValueError: if `n_classes` or `thresholds` is invalid.
  """
  thresholds = tuple(thresholds) if thresholds else tuple()
  if n_classes is None or n_classes < 2:
    raise ValueError(
        'n_classes must be > 1 for multi-class classification. '
        'Given: {}'.format(n_classes))
  for threshold in thresholds:
    if (threshold <= 0.0) or (threshold >= 1.0):
      raise ValueError(
          'thresholds must be in (0, 1) range. Given: {}'.format(threshold))
  if label_vocabulary is not None:
    if not isinstance(label_vocabulary, (list, tuple)):
      raise ValueError(
          'label_vocabulary must be a list or tuple. '
          'Given type: {}'.format(type(label_vocabulary)))
    if len(label_vocabulary) != n_classes:
      raise ValueError(
          'Length of label_vocabulary must be n_classes ({}). '
          'Given: {}'.format(n_classes, len(label_vocabulary)))
  if loss_fn:
    _validate_loss_fn_args(loss_fn)
  return _MultiLabelHead(
      n_classes=n_classes, weight_column=weight_column, thresholds=thresholds,
      label_vocabulary=label_vocabulary, loss_fn=loss_fn, name=name)


class _MultiLabelHead(head_lib._Head):  # pylint:disable=protected-access
  """`_Head` for multi-label classification."""

  def __init__(self,
               n_classes,
               weight_column=None,
               thresholds=None,
               label_vocabulary=None,
               loss_fn=None,
               name=None):
    self._n_classes = n_classes
    self._weight_column = weight_column
    self._thresholds = thresholds
    self._label_vocabulary = label_vocabulary
    self._loss_fn = loss_fn
    self._name = name

  @property
  def name(self):
    return self._name

  @property
  def logits_dimension(self):
    return self._n_classes

  def _process_labels(self, labels):
    if labels is None:
      raise ValueError(
          'You must provide a labels Tensor. Given: None. '
          'Suggested troubleshooting steps: Check that your data contain '
          'your label feature. Check that your input_fn properly parses and '
          'returns labels.')
    if isinstance(labels, sparse_tensor.SparseTensor):
      if labels.dtype == dtypes.string:
        label_ids_values = lookup_ops.index_table_from_tensor(
            vocabulary_list=tuple(self._label_vocabulary),
            name='class_id_lookup').lookup(labels.values)
        label_ids = sparse_tensor.SparseTensor(
            indices=labels.indices,
            values=label_ids_values,
            dense_shape=labels.dense_shape)
      else:
        label_ids = labels
      return math_ops.to_int64(
          sparse_ops.sparse_to_indicator(label_ids, self._n_classes))
    msg = ('labels shape must be [batch_size, {}]. '
           'Given: ').format(self._n_classes)
    labels_shape = array_ops.shape(labels)
    check_rank_op = control_flow_ops.Assert(
        math_ops.equal(array_ops.rank(labels), 2),
        data=[msg, labels_shape])
    check_label_dim = control_flow_ops.Assert(
        math_ops.equal(labels_shape[-1], self._n_classes),
        data=[msg, labels_shape])
    with ops.control_dependencies([check_rank_op, check_label_dim]):
      return array_ops.identity(labels)

  def create_loss(self, features, mode, logits, labels):
    """See `Head`."""
    del mode  # Unused for this head.
    processed_labels = self._process_labels(labels)
    if self._loss_fn:
      unweighted_loss = _call_loss_fn(
          loss_fn=self._loss_fn, labels=processed_labels, logits=logits,
          features=features)
    else:
      unweighted_loss = losses.sigmoid_cross_entropy(
          multi_class_labels=processed_labels, logits=logits,
          reduction=losses.Reduction.NONE)
      # Averages loss over classes.
      unweighted_loss = math_ops.reduce_mean(
          unweighted_loss, axis=-1, keep_dims=True)
    weights = head_lib._weights(features, self._weight_column)  # pylint:disable=protected-access,
    weighted_sum_loss = losses.compute_weighted_loss(
        unweighted_loss, weights=weights, reduction=losses.Reduction.SUM)
    # _weights() can return 1.
    example_weight_sum = math_ops.reduce_sum(
        weights * array_ops.ones_like(unweighted_loss))
    return head_lib.LossSpec(
        weighted_sum_loss=weighted_sum_loss,
        example_weight_sum=example_weight_sum,
        processed_labels=processed_labels)

  def create_estimator_spec(
      self, features, mode, logits, labels=None, train_op_fn=None):
    """See `Head`."""
    with ops.name_scope(self._name, 'head'):
      logits = head_lib._check_logits(logits, self.logits_dimension)  # pylint:disable=protected-access

      # Predict.
      pred_keys = prediction_keys.PredictionKeys
      with ops.name_scope(None, 'predictions', (logits,)):
        probabilities = math_ops.sigmoid(logits, name=pred_keys.PROBABILITIES)
        predictions = {
            pred_keys.LOGITS: logits,
            pred_keys.PROBABILITIES: probabilities,
        }
      if mode == model_fn.ModeKeys.PREDICT:
        classifier_output = head_lib._classification_output(  # pylint:disable=protected-access
            scores=probabilities, n_classes=self._n_classes,
            label_vocabulary=self._label_vocabulary)
        return model_fn.EstimatorSpec(
            mode=model_fn.ModeKeys.PREDICT,
            predictions=predictions,
            export_outputs={
                _DEFAULT_SERVING_KEY: classifier_output,
                head_lib._CLASSIFY_SERVING_KEY: classifier_output,  # pylint:disable=protected-access
                head_lib._PREDICT_SERVING_KEY: (  # pylint:disable=protected-access
                    export_output.PredictOutput(predictions))
            })

      (weighted_sum_loss, example_weight_sum,
       processed_labels) = self.create_loss(
           features=features, mode=mode, logits=logits, labels=labels)

      # Eval.
      if mode == model_fn.ModeKeys.EVAL:
        return model_fn.EstimatorSpec(
            mode=model_fn.ModeKeys.EVAL,
            predictions=predictions,
            loss=weighted_sum_loss,
            eval_metric_ops=self._eval_metric_ops(
                labels=processed_labels,
                probabilities=probabilities,
                weights=head_lib._weights(features, self._weight_column),  # pylint:disable=protected-access,
                weighted_sum_loss=weighted_sum_loss,
                example_weight_sum=example_weight_sum))

      # Train.
      if train_op_fn is None:
        raise ValueError('train_op_fn can not be None.')
    with ops.name_scope(''):
      summary.scalar(
          head_lib._summary_key(self._name, metric_keys.MetricKeys.LOSS),  # pylint:disable=protected-access
          weighted_sum_loss)
      summary.scalar(
          head_lib._summary_key(  # pylint:disable=protected-access
              self._name, metric_keys.MetricKeys.LOSS_MEAN),
          weighted_sum_loss / example_weight_sum)
    return model_fn.EstimatorSpec(
        mode=model_fn.ModeKeys.TRAIN,
        predictions=predictions,
        loss=weighted_sum_loss,
        train_op=train_op_fn(weighted_sum_loss))

  def _eval_metric_ops(self, labels, probabilities, weights, weighted_sum_loss,
                       example_weight_sum):
    """Returns a dict of metrics for eval_metric_ops."""
    with ops.name_scope(
        None, 'metrics',
        [labels, probabilities, weights, weighted_sum_loss, example_weight_sum
        ]):
      keys = metric_keys.MetricKeys
      metric_ops = {
          # Estimator already adds a metric for loss.
          head_lib._summary_key(self._name, keys.LOSS_MEAN):  # pylint:disable=protected-access
              metrics_lib.mean(
                  # Both values and weights here are reduced, scalar Tensors.
                  # values is the actual mean we want, but we pass the scalar
                  # example_weight_sum in order to return the correct update_op
                  # alongside the value_op for streaming metrics.
                  values=(weighted_sum_loss / example_weight_sum),
                  weights=example_weight_sum,
                  name=keys.LOSS_MEAN),
          head_lib._summary_key(self._name, keys.AUC):  # pylint:disable=protected-access
              metrics_lib.auc(labels=labels, predictions=probabilities,
                              weights=weights, name=keys.AUC),
          head_lib._summary_key(self._name, keys.AUC_PR):  # pylint:disable=protected-access
              metrics_lib.auc(labels=labels, predictions=probabilities,
                              weights=weights, curve='PR',
                              name=keys.AUC_PR),
      }
      for threshold in self._thresholds:
        accuracy_key = keys.ACCURACY_AT_THRESHOLD % threshold
        metric_ops[head_lib._summary_key(self._name, accuracy_key)] = (  # pylint:disable=protected-access
            head_lib._accuracy_at_threshold(  # pylint:disable=protected-access
                labels=labels,
                predictions=probabilities,
                weights=weights,
                threshold=threshold,
                name=accuracy_key))
        # Precision for positive examples.
        precision_key = keys.PRECISION_AT_THRESHOLD % threshold
        metric_ops[head_lib._summary_key(self._name, precision_key)] = (  # pylint:disable=protected-access
            head_lib._precision_at_threshold(  # pylint:disable=protected-access
                labels=labels,
                predictions=probabilities,
                weights=weights,
                threshold=threshold,
                name=precision_key))
        # Recall for positive examples.
        recall_key = keys.RECALL_AT_THRESHOLD % threshold
        metric_ops[head_lib._summary_key(self._name, recall_key)] = (  # pylint:disable=protected-access
            head_lib._recall_at_threshold(  # pylint:disable=protected-access
                labels=labels,
                predictions=probabilities,
                weights=weights,
                threshold=threshold,
                name=recall_key))
    return metric_ops


def _validate_loss_fn_args(loss_fn):
  """Validates loss_fn arguments.

  Required arguments: labels, logits.
  Optional arguments: features.

  Args:
    loss_fn: The loss function.
  Raises:
    ValueError: If the signature is unexpected.
  """
  loss_fn_args = util.fn_args(loss_fn)
  for required_arg in ['labels', 'logits']:
    if required_arg not in loss_fn_args:
      raise ValueError(
          'loss_fn must contain argument: {}. '
          'Given arguments: {}'.format(required_arg, loss_fn_args))
  invalid_args = list(set(loss_fn_args) - set(['labels', 'logits', 'features']))
  if invalid_args:
    raise ValueError('loss_fn has unexpected args: {}'.format(invalid_args))


def _call_loss_fn(loss_fn, labels, logits, features):
  """Calls loss_fn and checks the returned shape.

  Args:
    loss_fn: The loss function.
    labels: Processed labels Tensor.
    logits: Logits Tensor of shape [batch_size, logits_dimension].
    features: Features dict.
  Returns:
    Loss Tensor with shape [batch_size, 1].
  """
  loss_fn_args = util.fn_args(loss_fn)
  kwargs = {}
  if 'features' in loss_fn_args:
    kwargs['features'] = features
  unweighted_loss = loss_fn(labels=labels, logits=logits, **kwargs)
  batch_size = array_ops.shape(logits)[0]
  loss_shape = array_ops.shape(unweighted_loss)
  check_shape_op = control_flow_ops.Assert(
      math_ops.reduce_all(math_ops.equal(loss_shape, [batch_size, 1])),
      data=[
          'loss_fn must return Tensor of shape [batch_size, 1]. Given: ',
          loss_shape])
  with ops.control_dependencies([check_shape_op]):
    return array_ops.identity(unweighted_loss)
