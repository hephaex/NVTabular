#
# Copyright (c) 2020, NVIDIA CORPORATION.
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
#

import math

import cudf
import numpy as np
import pytest
from cudf.tests.utils import assert_eq

import nvtabular as nvt
import nvtabular.io
import nvtabular.ops as ops
from tests.conftest import cleanup, mycols_csv, mycols_pq


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["x"], None])
def test_minmax(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y"]
    label_name = ["label"]

    config = nvtabular.workflow.get_new_config()
    config["PP"]["all"] = [ops.MinMax(columns=op_columns)]

    processor = nvtabular.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)
    x_min = df["x"].min()

    assert x_min == pytest.approx(processor.stats["mins"]["x"], 1e-2)
    x_max = df["x"].max()
    assert x_max == pytest.approx(processor.stats["maxs"]["x"], 1e-2)
    if not op_columns:
        name_min = min(df["name-string"].tolist())
        name_max = max(df["name-string"].tolist())
        assert name_min == processor.stats["mins"]["name-string"]
        y_max = df["y"].max()
        y_min = df["y"].min()
        assert y_max == processor.stats["maxs"]["y"]
        assert name_max == processor.stats["maxs"]["name-string"]
        assert y_min == processor.stats["mins"]["y"]
    return processor.ds_exports


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["x"], None])
def test_moments(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    config = nvt.workflow.get_new_config()
    config["PP"]["continuous"] = [ops.Moments(columns=op_columns)]

    processor = nvt.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)

    assert df.x.count() == processor.stats["counts"]["x"]
    assert df.x.count() == 4321

    # Check mean and std
    assert math.isclose(df.x.mean(), processor.stats["means"]["x"], rel_tol=1e-4)
    assert math.isclose(df.x.std(), processor.stats["stds"]["x"], rel_tol=1e-3)
    if not op_columns:
        assert math.isclose(df.y.mean(), processor.stats["means"]["y"], rel_tol=1e-4)
        assert math.isclose(df.id.mean(), processor.stats["means"]["id"], rel_tol=1e-4)

        assert math.isclose(df.y.std(), processor.stats["stds"]["y"], rel_tol=1e-3)
        assert math.isclose(df.id.std(), processor.stats["stds"]["id"], rel_tol=1e-3)
    return processor.ds_exports


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["name-string"], None])
def test_encoder(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    config = nvt.workflow.get_new_config()
    config["PP"]["categorical"] = [ops.Encoder(columns=op_columns)]

    processor = nvt.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)

    # Check that categories match
    if engine == "parquet" and not op_columns:
        cats_expected0 = df["name-cat"].unique().values_to_string()
        cats0 = processor.stats["encoders"]["name-cat"].get_cats().values_to_string()
        assert cats0 == ["None"] + cats_expected0
    cats_expected1 = df["name-string"].unique().values_to_string()
    cats1 = processor.stats["encoders"]["name-string"].get_cats().values_to_string()
    assert cats1 == ["None"] + cats_expected1
    return processor.ds_exports


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["x"], None])
def test_median(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    config = nvt.workflow.get_new_config()
    config["PP"]["continuous"] = [ops.Median(columns=op_columns)]

    processor = nvt.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)

    # Check median (TODO: Improve the accuracy)
    x_median = df.x.dropna().quantile(0.5, interpolation="linear")
    assert math.isclose(x_median, processor.stats["medians"]["x"], rel_tol=1e1)
    if not op_columns:
        y_median = df.y.dropna().quantile(0.5, interpolation="linear")
        id_median = df.id.dropna().quantile(0.5, interpolation="linear")
        assert math.isclose(y_median, processor.stats["medians"]["y"], rel_tol=1e1)
        assert math.isclose(id_median, processor.stats["medians"]["id"], rel_tol=1e1)
    return processor.ds_exports


@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["x"], None])
def test_log(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cont_names = ["x", "y", "id"]
    log_op = ops.LogOp(columns=op_columns)

    columns_ctx = {}
    columns_ctx["continuous"] = {}
    columns_ctx["continuous"]["base"] = cont_names

    for gdf in dataset:
        new_gdf = log_op.apply_op(gdf, columns_ctx, "continuous")
        assert new_gdf[cont_names] == np.log(gdf[cont_names].astype(np.float32))


@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("op_columns", [["name-string"], None])
def test_hash_bucket(tmpdir, df, dataset, gpu_memory_frac, engine, op_columns):
    cat_names = ["name-string"]

    if op_columns is None:
        num_buckets = 10
    else:
        num_buckets = {column: 10 for column in op_columns}
    hash_bucket_op = ops.HashBucket(num_buckets)

    columns_ctx = {}
    columns_ctx["categorical"] = {}
    columns_ctx["categorical"]["base"] = cat_names

    # check sums for determinancy
    checksums = []
    for gdf in dataset:
        new_gdf = hash_bucket_op.apply_op(gdf, columns_ctx, "categorical")
        assert np.all(new_gdf[cat_names].values >= 0)
        assert np.all(new_gdf[cat_names].values <= 9)
        checksums.append(new_gdf[cat_names].sum().values)

    for checksum, gdf in zip(checksums, dataset):
        new_gdf = hash_bucket_op.apply_op(gdf, columns_ctx, "categorical")
        assert np.all(new_gdf[cat_names].sum().values == checksum)


@pytest.mark.parametrize("engine", ["parquet"])
def test_fill_missing(tmpdir, df, dataset, engine):
    op = nvt.ops.FillMissing(42)

    cont_names = ["x", "y"]
    columns_ctx = {}
    columns_ctx["continuous"] = {}
    columns_ctx["continuous"]["base"] = cont_names

    transformed = cudf.concat([op.apply_op(df, columns_ctx, "continuous") for df in dataset])
    assert_eq(transformed[cont_names], df[cont_names].dropna(42))


@pytest.mark.parametrize("engine", ["parquet"])
def test_dropna(tmpdir, df, dataset, engine):
    dropna = ops.Dropna()
    columns = mycols_pq if engine == "parquet" else mycols_csv

    columns_ctx = {}
    columns_ctx["all"] = {}
    columns_ctx["all"]["base"] = columns

    for gdf in dataset:
        new_gdf = dropna.apply_op(gdf, columns_ctx, "all")
        assert new_gdf.columns.all() == gdf.columns.all()
        assert new_gdf.isnull().all().sum() < 1, "null values exist"
