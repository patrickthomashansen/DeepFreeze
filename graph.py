#!/usr/bin/env python

"""
Author: Patrick Hansen
Project: FixyNN

Defines Graph and Layer classes used for intermediate representation
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import json

DEPTHWISE_SEPARABLE_CONV_2D = "ds_conv_2d"
DEPTHWISE_CONV_2D = "dw_conv_2d"
CONV_2D = "conv_2d"
DENSE = "dense"
MAX_POOL_2D = "max_pool_2d"
AVG_POOL_2D = "avg_pool_2d"
FLATTEN = "flatten"

LAYER_TYPES_CONV = [DEPTHWISE_SEPARABLE_CONV_2D, DEPTHWISE_CONV_2D, CONV_2D]
LAYER_TYPES_POOL = [MAX_POOL_2D, AVG_POOL_2D]
LAYER_TYPES_2D = LAYER_TYPES_CONV + LAYER_TYPES_POOL
LAYER_TYPES_TRAINABLE = LAYER_TYPES_CONV + [DENSE]


def get_tf_graph(meta_graph_filepath):
    tf.train.import_meta_graph(meta_graph_filepath)
    return tf.get_default_graph()

def get_endpoints(endpoints_filepath, graph):
    with open(endpoints_filepath, "r") as f:
        endpoints_by_name = json.load(f)
    endpoints = {k: graph.get_tensor_by_name(v) for k, v in endpoints_by_name.iteritems()}
    return endpoints

def get_layer_name(tensor, endpoints):
    """Find the name given to the endpoint corresponding to node"""
    for name, _tensor in endpoints.iteritems():
        if tensor == _tensor:
            return name
    return None

def get_tensor_shape(tensor):
    """Returns the tensor shape as a ist of ints/None"""
    shape = []
    for size in tensor.shape:
        try:
            shape.append(int(size))
        except:
            shape.append(None)
    return shape

def get_variable_from_graph(graph, ckpt, variable):
    """Extract the value of a variable from a checkpoint"""
    with tf.Session(graph=graph) as sess:
        tf.train.Saver().restore(sess, ckpt)
        return sess.run(variable)


class Graph():
    def __init__(self, name):
        self.name = name
        self.layers = []
        self.removed_layer_names = []

    def add_layer(self, layer):
        connections = layer.input_names + layer.output_names
        for layer_name in self.removed_layer_names:
            if layer_name in layer.input_names:
                layer.input_names.remove(layer_name)
            if layer_name in layer.output_names:
                layer.output_names.remove(layer_name)
        self.layers.append(layer)

    def remove_layer(self, layer):
        layer_name = layer.name
        for layer in self.layers:
            if layer_name in layer.input_names:
                layer.input_names.remove(layer_name)
            if layer_name in layer.output_names:
                layer.output_names.remove(layer_name)
        self.removed_layer_names.append(layer_name)

    def remove_layer_references(self, layer):
        self.remove_layer(layer)

    def find_layer(self, name):
        for layer in self.layers:
            if layer.name == name:
                return layer
        return None

    def get_input_layer(self):
        for layer in self.layers:
            if not layer.input_names:
                return layer
        return None

    def get_output_layer(self):
        for layer in self.layers:
            if not layer.output_names:
                return layer
        return None

    def get_next_layer(self, cur_layer):
        if cur_layer and cur_layer.output_names:
            next_layer_name = cur_layer.output_names[0] # TODO: enable branching
            next_layer = self.find_layer(next_layer_name)
            return next_layer
        else:
            return None

    def get_ordered_layers(self):
        ordered = []
        cur_layer = self.get_input_layer()
        while cur_layer:
            ordered += [cur_layer]
            cur_layer = self.get_next_layer(cur_layer)
        return ordered

    def print(self):
        if self.name:
            print("GRAPH INFO: name: %s" % self.name)
        ordered = self.get_ordered_layers()
        ordered_names = [layer.name for layer in ordered]
        print("GRAPH INFO: layers: %s\n" % " -> ".join(ordered_names))
        for layer in ordered:
            layer.print()


class Layer():
    def __init__(self, name, endpoints, graph, ckpt):
        self._endpoints = endpoints
        self._tensor = self._endpoints[name]
        self._layer_ops = self.__get_layer_ops()

        self.name = name
        self.op_type = self.__get_op_type()

        self.input_names = self.__get_input_layer_names()
        self.output_names = self.__get_output_layer_names()
        self.input_shapes = self.__get_input_shapes()
        self.output_shape = self.__get_output_shape()

        if self.op_type in LAYER_TYPES_TRAINABLE:
            self.weights = self.__get_weights(graph, ckpt)
            self.bias = self.__get_bias(graph, ckpt)

        if self.op_type in LAYER_TYPES_2D:
            self.kernel_size = self.__get_kernel_size()
            self.strides = self.__get_strides()
            self.padding = self.__get_padding()

        self.has_relu = bool(self.__get_op_by_type("Relu"))

    def __get_input_layer_names(self, tensor=None):
        """Return a list of all layer names that are direct inputs to this layer"""
        if tensor == None:
            tensor = self._tensor
        inputs = []
        for inp in tensor.op.inputs:
            if inp in self._endpoints.values():
                inputs += [get_layer_name(inp, self._endpoints)]
            else:
                inputs += self.__get_input_layer_names(inp)
        return list(set(inputs))

    def __get_output_layer_names(self):
        """Return a list of all layer names that are direct outputs of this layer"""
        outputs = []
        for name, tensor in self._endpoints.iteritems():
            if self.name in self.__get_input_layer_names(tensor):
                outputs += [name]
        return outputs

    def __get_layer_ops(self, tensor=None):
        """Return all list of all ops in this layer"""
        if tensor == None:
            tensor = self._tensor
        layer_ops = [tensor.op]
        for inp in tensor.op.inputs:
            if not inp in self._endpoints.values():
                layer_ops += self.__get_layer_ops(inp)
        return list(set(layer_ops))

    def __get_op_type(self):
        """Determine the operation type of this layer"""
        layer_ops_types = [op.type for op in self._layer_ops]
        if "DepthwiseConv2dNative" in layer_ops_types and \
                "Conv2D" in layer_ops_types:
            return DEPTHWISE_SEPARABLE_CONV_2D
        elif "DepthwiseConv2dNative" in layer_ops_types:
            return DEPTHWISE_CONV_2D
        elif "Conv2D" in layer_ops_types:
            return CONV_2D
        elif "MatMul" in layer_ops_types:
            return DENSE
        elif "MaxPool" in layer_ops_types:
            return MAX_POOL_2D
        elif "AvgPool" in layer_ops_types:
            return AVG_POOL_2D
        elif "Reshape" in layer_ops_types:
            return FLATTEN
        else:
            raise Exception("Could not match layer with a known op type")

    def __get_op_by_type(self, op_type):
        for op in self._layer_ops:
            if op.type == op_type:
                return op
        return None

    def __get_input_shapes(self):
        """Return a list of all input activation tensor shapes to node"""
        if not self.input_names:
            tensor = self._tensor
            while tensor.op.inputs:
                shape = get_tensor_shape(tensor)
                tensor = tensor.op.inputs[0]
                if not get_tensor_shape(tensor) or \
                        (self.op_type in LAYER_TYPES_2D and len(get_tensor_shape(tensor)) != 4):
                    return [shape]
            return [get_tensor_shape(tensor)]
        else:
            return [get_tensor_shape(self._endpoints[x]) for x in self.input_names]

    def __get_output_shape(self):
        return get_tensor_shape(self._tensor)

    def __get_weights(self, graph, ckpt):
        """Extract weight parameters from a layer"""
        if self.op_type == DEPTHWISE_SEPARABLE_CONV_2D:
            depthwise_weights = self.__get_op_by_type("DepthwiseConv2dNative").inputs[1]
            pointwise_weights = self.__get_op_by_type("Conv2D").inputs[1]
            return [
                get_variable_from_graph(graph, ckpt, depthwise_weights),
                get_variable_from_graph(graph, ckpt, pointwise_weights)
            ]
        elif self.op_type == DEPTHWISE_CONV_2D:
            weights = self.__get_op_by_type("DepthwiseConv2dNative").inputs[1]
            return get_variable_from_graph(graph, ckpt, weights)
        elif self.op_type == CONV_2D:
            weights = self.__get_op_by_type("Conv2D").inputs[1]
            return get_variable_from_graph(graph, ckpt, weights)
        elif self.op_type == DENSE:
            weights = self.__get_op_by_type("MatMul").inputs[1]
            return get_variable_from_graph(graph, ckpt, weights)
        else:
            raise Exception("No weights found in layer: %s" % self.name)

    def __get_bias(self, graph, ckpt):
        """Extract bias parameters from a layer"""
        if self.__get_op_by_type("BiasAdd"):
            bias = self.__get_op_by_type("BiasAdd").inputs[1]
            return get_variable_from_graph(graph, ckpt, bias)
        elif self.op_type == DENSE and __get_op_by_type("Add"):
            bias = self.__get_op_by_type("Add").inputs[1]
            return get_variable_from_graph(graph, ckpt, bias)
        else:
            raise Exception("No bias found in layer: %s" % self.name)

    def __get_batch_norm(self, graph, ckpt):
        pass # TODO

    def __get_2d_op(self):
        """Returns the desired 2d op for the given layer type"""
        if self.op_type in [DEPTHWISE_SEPARABLE_CONV_2D, DEPTHWISE_CONV_2D]:
            return self.__get_op_by_type("DepthwiseConv2dNative")
        elif self.op_type == CONV_2D:
            return self.__get_op_by_type("Conv2D")
        elif self.op_type == MAX_POOL_2D:
            return self.__get_op_by_type("MaxPool")
        elif self.op_type == AVG_POOL_2D:
            return self.__get_op_by_type("AvgPool")
        else:
            raise Exception("No 2d operations in layer: %s" % self.name)

    def __get_kernel_size(self):
        if self.op_type == DEPTHWISE_SEPARABLE_CONV_2D:
            return self.weights[0].shape[0:2]
        elif self.op_type in [DEPTHWISE_CONV_2D, CONV_2D]:
            return self.weights.shape[0:2]
        elif self.op_type in [MAX_POOL_2D, AVG_POOL_2D]:
            op = self.__get_2d_op()
            kernel_size = op.get_attr("ksize")
            return (int(kernel_size[1]), int(kernel_size[2]))
        else:
            raise Exception("No kernel size for layer: %s" % self.name)

    def __get_strides(self):
        op = self.__get_2d_op()
        strides = op.get_attr("strides")
        return (int(strides[1]), int(strides[2]))

    def __get_padding(self):
        op = self.__get_2d_op()
        padding = op.get_attr("padding")
        return (padding)

    def print(self):
        def print_info(string):
            print("LAYER INFO: %s" % string)
            
        print_info("name: %s" % self.name)
        print_info("op type: %s" % self.op_type)
        print_info("inputs: %s" % self.input_names)
        print_info("outputs: %s" % self.output_names)
        print_info("input shapes: %s" % self.input_shapes)
        print_info("output shape: %s" % self.output_shape)
        if self.op_type in LAYER_TYPES_TRAINABLE:
            if self.op_type == DEPTHWISE_SEPARABLE_CONV_2D:
                print_info("depthwise weights shape: %s" % (self.weights[0].shape,))
                print_info("pointwise weights shape: %s" % (self.weights[1].shape,))
            else:
                print_info("weights shape: %s" % (self.weights.shape,))
            print_info("bias shape: %s" % (self.bias.shape,))
        if self.op_type in LAYER_TYPES_2D:
            print_info("kernel size: %s" % (self.kernel_size,))
            print_info("strides: %s" % (self.strides,))
            print_info("padding: %s" % self.padding)
        print("")


def parse_tf_graph(
    model_name, endpoints_filepath, meta_filepath, checkpoint_filepath, only_2d=False
):
    """Parses a Tensorflow model into an intermediate representation"""
    tf_graph = get_tf_graph(meta_filepath)
    endpoints = get_endpoints(endpoints_filepath, tf_graph)

    graph = Graph(model_name)
    for layer_name in endpoints.keys():
        layer = Layer(layer_name, endpoints, tf_graph, checkpoint_filepath)
        if only_2d and not layer.op_type in LAYER_TYPES_2D:
            graph.remove_layer_references(layer)
        else:
            graph.add_layer(layer)
    graph.print()
    return graph
