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

import glob
import math

import cudf
import numpy as np
import pytest
from cudf.tests.utils import assert_eq

import nvtabular as nvt
import nvtabular.io
import nvtabular.ops as ops
from tests.conftest import allcols_csv, cleanup, mycols_csv, mycols_pq


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("dump", [True, False])
@pytest.mark.parametrize("op_columns", [["x"], None])
def test_gpu_workflow_api(tmpdir, df, dataset, gpu_memory_frac, engine, dump, op_columns):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    processor = nvt.Workflow(cat_names=cat_names, cont_names=cont_names, label_name=label_name,)

    processor.add_feature([ops.ZeroFill(columns=op_columns), ops.LogOp()])
    processor.add_preprocess(ops.Normalize())
    processor.add_preprocess(ops.Categorify())
    processor.finalize()

    processor.update_stats(dataset)

    if dump:
        config_file = tmpdir + "/temp.yaml"
        processor.save_stats(config_file)
        processor.clear_stats()
        processor.load_stats(config_file)

    def get_norms(tar: cudf.Series):
        gdf = tar.fillna(0)
        gdf = gdf * (gdf >= 0).astype("int")
        gdf = np.log(gdf + 1)
        return gdf

    # Check mean and std - No good right now we have to add all other changes; Zerofill, Log

    if not op_columns:
        assert math.isclose(get_norms(df.y).mean(), processor.stats["means"]["y"], rel_tol=1e-1,)
        assert math.isclose(get_norms(df.y).std(), processor.stats["stds"]["y"], rel_tol=1e-1,)
    assert math.isclose(get_norms(df.x).mean(), processor.stats["means"]["x"], rel_tol=1e-1,)
    assert math.isclose(get_norms(df.x).std(), processor.stats["stds"]["x"], rel_tol=1e-1,)

    # Check that categories match
    if engine == "parquet":
        cats_expected0 = df["name-cat"].unique().values_to_string()
        cats0 = processor.stats["encoders"]["name-cat"].get_cats().values_to_string()
        # adding the None entry as a string because of move from gpu
        assert cats0 == ["None"] + cats_expected0
    cats_expected1 = df["name-string"].unique().values_to_string()
    cats1 = processor.stats["encoders"]["name-string"].get_cats().values_to_string()
    # adding the None entry as a string because of move from gpu
    assert cats1 == ["None"] + cats_expected1

    # Write to new "shuffled" and "processed" dataset
    processor.write_to_dataset(tmpdir, dataset, nfiles=10, shuffle=True, apply_ops=True)

    data_itr_2 = nvtabular.io.GPUDatasetIterator(
        glob.glob(str(tmpdir) + "/ds_part.*.parquet"),
        use_row_groups=True,
        gpu_memory_frac=gpu_memory_frac,
    )

    df_pp = None
    for chunk in data_itr_2:
        df_pp = cudf.concat([df_pp, chunk], axis=0) if df_pp else chunk

    if engine == "parquet":
        assert df_pp["name-cat"].dtype == "int64"
    assert df_pp["name-string"].dtype == "int64"

    num_rows, num_row_groups, col_names = cudf.io.read_parquet_metadata(str(tmpdir) + "/_metadata")
    assert num_rows == len(df_pp)
    return processor.ds_exports


@pytest.mark.parametrize("batch", [0, 100, 1000])
def test_gpu_file_iterator_parquet(datasets, batch):
    paths = glob.glob(str(datasets["parquet"]) + "/*.parquet")
    df_expect = cudf.read_parquet(paths[0], columns=mycols_pq)
    df_itr = cudf.DataFrame()
    data_itr = nvtabular.io.GPUFileIterator(
        paths[0], batch_size=batch, gpu_memory_frac=0.01, columns=mycols_pq
    )
    for data_gd in data_itr:
        df_itr = cudf.concat([df_itr, data_gd], axis=0) if df_itr else data_gd

    assert_eq(df_itr.reset_index(drop=True), df_expect.reset_index(drop=True))


@pytest.mark.parametrize("batch", [0, 100, 1000])
@pytest.mark.parametrize("dskey", ["csv", "csv-no-header"])
def test_gpu_file_iterator_csv(datasets, batch, dskey):
    paths = glob.glob(str(datasets[dskey]) + "/*.csv")
    names = allcols_csv if dskey == "csv-no-header" else None
    header = None if dskey == "csv-no-header" else 0
    df_expect = cudf.read_csv(paths[0], header=header, names=names)[mycols_csv]
    df_expect["id"] = df_expect["id"].astype("int64")
    df_itr = cudf.DataFrame()
    data_itr = nvtabular.io.GPUFileIterator(
        paths[0], batch_size=batch, gpu_memory_frac=0.01, columns=mycols_csv, names=names,
    )
    for data_gd in data_itr:
        df_itr = cudf.concat([df_itr, data_gd], axis=0) if df_itr else data_gd

    assert_eq(df_itr.reset_index(drop=True), df_expect.reset_index(drop=True))


@pytest.mark.parametrize("batch", [0, 100, 1000])
def test_gpu_dataset_iterator_parquet(datasets, batch):
    paths = glob.glob(str(datasets["parquet"]) + "/*.parquet")
    df_expect = cudf.read_parquet(paths[0], columns=mycols_pq)
    df_expect = cudf.concat([df_expect, cudf.read_parquet(paths[1], columns=mycols_pq)], axis=0)
    df_itr = cudf.DataFrame()
    data_itr = nvtabular.io.GPUDatasetIterator(
        paths, batch_size=batch, gpu_memory_frac=0.01, columns=mycols_pq
    )
    for data_gd in data_itr:
        df_itr = cudf.concat([df_itr, data_gd], axis=0) if df_itr else data_gd

    assert_eq(df_itr.reset_index(drop=True), df_expect.reset_index(drop=True))


@pytest.mark.parametrize("batch", [0, 100, 1000])
@pytest.mark.parametrize("engine", ["csv", "csv-no-header"])
def test_gpu_dataset_iterator_csv(datasets, df, dataset, batch, engine):
    df_itr = cudf.DataFrame()
    for data_gd in dataset:
        df_itr = cudf.concat([df_itr, data_gd], axis=0) if df_itr else data_gd
    assert_eq(df_itr.reset_index(drop=True), df.reset_index(drop=True))


@cleanup
@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("dump", [True, False])
def test_gpu_workflow(tmpdir, df, dataset, gpu_memory_frac, engine, dump):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    config = nvt.workflow.get_new_config()
    config["FE"]["continuous"] = [ops.ZeroFill()]
    config["PP"]["continuous"] = [[ops.ZeroFill(), ops.Normalize()]]
    config["PP"]["categorical"] = [ops.Categorify()]

    processor = nvt.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)
    if dump:
        config_file = tmpdir + "/temp.yaml"
        processor.save_stats(config_file)
        processor.clear_stats()
        processor.load_stats(config_file)

    def get_norms(tar: cudf.Series):
        gdf = tar.fillna(0)
        gdf = gdf * (gdf >= 0).astype("int")
        return gdf

    assert math.isclose(get_norms(df.x).mean(), processor.stats["means"]["x"], rel_tol=1e-4)
    assert math.isclose(get_norms(df.y).mean(), processor.stats["means"]["y"], rel_tol=1e-4)
    #     assert math.isclose(get_norms(df.id).mean(),
    #                         processor.stats["means"]["id_ZeroFill_LogOp"], rel_tol=1e-4)
    assert math.isclose(get_norms(df.x).std(), processor.stats["stds"]["x"], rel_tol=1e-3)
    assert math.isclose(get_norms(df.y).std(), processor.stats["stds"]["y"], rel_tol=1e-3)
    #     assert math.isclose(get_norms(df.id).std(),
    #                         processor.stats["stds"]["id_ZeroFill_LogOp"], rel_tol=1e-3)

    # Check that categories match
    if engine == "parquet":
        cats_expected0 = df["name-cat"].unique().values_to_string()
        cats0 = processor.stats["encoders"]["name-cat"].get_cats().values_to_string()
        # adding the None entry as a string because of move from gpu
        assert cats0 == ["None"] + cats_expected0
    cats_expected1 = df["name-string"].unique().values_to_string()
    cats1 = processor.stats["encoders"]["name-string"].get_cats().values_to_string()
    # adding the None entry as a string because of move from gpu
    assert cats1 == ["None"] + cats_expected1

    # Write to new "shuffled" and "processed" dataset
    processor.write_to_dataset(tmpdir, dataset, nfiles=10, shuffle=True, apply_ops=True)

    data_itr_2 = nvtabular.io.GPUDatasetIterator(
        glob.glob(str(tmpdir) + "/ds_part.*.parquet"),
        use_row_groups=True,
        gpu_memory_frac=gpu_memory_frac,
    )

    df_pp = None
    for chunk in data_itr_2:
        df_pp = cudf.concat([df_pp, chunk], axis=0) if df_pp else chunk

    if engine == "parquet":
        assert df_pp["name-cat"].dtype == "int64"
    assert df_pp["name-string"].dtype == "int64"

    num_rows, num_row_groups, col_names = cudf.io.read_parquet_metadata(str(tmpdir) + "/_metadata")
    assert num_rows == len(df_pp)
    return processor.ds_exports


@pytest.mark.parametrize("gpu_memory_frac", [0.01, 0.1])
@pytest.mark.parametrize("engine", ["parquet", "csv", "csv-no-header"])
@pytest.mark.parametrize("dump", [True, False])
@pytest.mark.parametrize("replace", [True, False])
def test_gpu_workflow_config(tmpdir, df, dataset, gpu_memory_frac, engine, dump, replace):
    cat_names = ["name-cat", "name-string"] if engine == "parquet" else ["name-string"]
    cont_names = ["x", "y", "id"]
    label_name = ["label"]

    config = nvt.workflow.get_new_config()
    # add operators with dependencies
    config["FE"]["continuous"] = [[ops.FillMissing(replace=replace), ops.LogOp(replace=replace)]]
    config["PP"]["continuous"] = [[ops.LogOp(replace=replace), ops.Normalize()]]
    config["PP"]["categorical"] = [ops.Categorify()]

    processor = nvt.Workflow(
        cat_names=cat_names, cont_names=cont_names, label_name=label_name, config=config,
    )

    processor.update_stats(dataset)

    if dump:
        config_file = tmpdir + "/temp.yaml"
        processor.save_stats(config_file)
        processor.clear_stats()
        processor.load_stats(config_file)

    def get_norms(tar: cudf.Series):
        ser_median = tar.dropna().quantile(0.5, interpolation="linear")
        gdf = tar.fillna(ser_median)
        gdf = np.log(gdf + 1)
        return gdf

    # Check mean and std - No good right now we have to add all other changes; Zerofill, Log

    concat_ops = "_FillMissing_LogOp"
    if replace:
        concat_ops = ""
    assert math.isclose(
        get_norms(df.x).mean(), processor.stats["means"]["x" + concat_ops], rel_tol=1e-1,
    )
    assert math.isclose(
        get_norms(df.y).mean(), processor.stats["means"]["y" + concat_ops], rel_tol=1e-1,
    )

    assert math.isclose(
        get_norms(df.x).std(), processor.stats["stds"]["x" + concat_ops], rel_tol=1e-1,
    )
    assert math.isclose(
        get_norms(df.y).std(), processor.stats["stds"]["y" + concat_ops], rel_tol=1e-1,
    )

    # Check that categories match
    if engine == "parquet":
        cats_expected0 = df["name-cat"].unique().values_to_string()
        cats0 = processor.stats["encoders"]["name-cat"].get_cats().values_to_string()
        # adding the None entry as a string because of move from gpu
        assert cats0 == ["None"] + cats_expected0
    cats_expected1 = df["name-string"].unique().values_to_string()
    cats1 = processor.stats["encoders"]["name-string"].get_cats().values_to_string()
    # adding the None entry as a string because of move from gpu
    assert cats1 == ["None"] + cats_expected1

    # Write to new "shuffled" and "processed" dataset
    processor.write_to_dataset(tmpdir, dataset, nfiles=10, shuffle=True, apply_ops=True)

    data_itr_2 = nvtabular.io.GPUDatasetIterator(
        glob.glob(str(tmpdir) + "/ds_part.*.parquet"),
        use_row_groups=True,
        gpu_memory_frac=gpu_memory_frac,
    )

    df_pp = None
    for chunk in data_itr_2:
        df_pp = cudf.concat([df_pp, chunk], axis=0) if df_pp else chunk

    if engine == "parquet":
        assert df_pp["name-cat"].dtype == "int64"
    assert df_pp["name-string"].dtype == "int64"

    num_rows, num_row_groups, col_names = cudf.io.read_parquet_metadata(str(tmpdir) + "/_metadata")
    assert num_rows == len(df_pp)
    return processor.ds_exports
