# props/ — Materials Project 材料属性数据集

## 概述

本目录存放从 **Materials Project (MP)** 数据库下载的材料属性数据。数据来源于 `download_props.py`，针对带隙 ≥ 1 eV 的含 Na 材料子集（8253 个材料），从 MP 的 14 个 API 端点批量拉取。

每个材料以其 `material_id`（如 `mp-1001112`）标识，对应的 JSON 文件存放在各端点子目录下。

## 数据覆盖总览

| 端点 | 有数据 | 文件数 | 说明 |
|------|--------|--------|------|
| summary | ✅ | 8253 | 结构 + 带隙 + 能量 + 对称性等概要信息 |
| thermo | ✅ | 8253 | 热力学性质（每材料 2 个条目） |
| magnetism | ✅ | 8253 | 磁性性质 |
| oxidation_states | ✅ | 8253 | 氧化态（Bond Valence Analysis） |
| chemenv | ✅ | 8253 | 配位化学环境 |
| bonds | ✅ | 8253 | 键信息（CrystalNN） |
| provenance | ✅ | 6144 | 数据来源与参考文献 |
| robocrys | ✅ | 3685 | 晶体学自然语言描述 |
| dielectric | ✅ | 548 | 介电性质（仅非金属） |
| elasticity | ✅ | 225 | 弹性性质（仅机械稳定的非金属） |
| piezoelectric | ✅ | 240 | 压电性质（仅非中心对称的非金属） |
| absorption | ✅ | 74 | 光吸收谱 |
| surface_properties | ❌ | 0 | 无数据（所有材料状态为 empty） |
| grain_boundaries | ❌ | 0 | 无数据（所有材料状态为 empty） |

## 各端点详细字段

### 1. summary/ — 概要属性（8253 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `material_id` | str | MP 材料 ID（如 `mp-1001112`） |
| `formula_pretty` | str | 化学式（如 `Na3Sc2(PO4)3`） |
| `formula_anonymous` | str | 匿名化化学式 |
| `nsites` | int | 晶胞原子数 |
| `nelements` | int | 元素种类数 |
| `elements` | list[str] | 元素列表 |
| `composition` | dict | 各元素含量 |
| `symmetry` | dict | 对称性（symbol, number, crystal_system, hall, point_group） |
| `structure` | dict | 完整晶体结构（晶格、位点坐标、occupancy 等） |
| `band_gap` | float | 带隙（eV） |
| `cbm` | float | 导带底能量 |
| `vbm` | float | 价带顶能量 |
| `is_metal` | bool | 是否为金属 |
| `is_stable` | bool | 是否在凸包上（热力学稳定） |
| `energy_above_hull` | float | 离凸包能量（meV/atom） |
| `formation_energy_per_atom` | float | 每原子形成能（eV/atom） |
| `energy_per_atom` | float | 每原子总能量 |
| `density` | float | 密度（g/cm³） |
| `density_atomic` | float | 原子密度 |
| `volume` | float | 晶胞体积（Å³） |
| `total_magnetization` | float | 总磁化强度 |

### 2. thermo/ — 热力学性质（8253 个 JSON）

注意：顶层是 **长度为 2 的 list**（非 dict），包含两个 `ThermoDoc` 对象。

每个元素包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `thermo_type` | str | 热力学类型 |
| `energy` | float | 能量 |
| `energy_per_atom` | float | 每原子能量 |
| `enthalpy` | float | 焓 |
| `entropy` | float | 熵（部分可能为 None） |
| `free_energy` | float | 自由能 |
| `temperature` | float | 温度 |
| `pressure` | float | 压强 |
| `entries` | list | 包含的相条目 |
| `decomposes_to` | list | 分解产物 |
| `decomposition_enthalpy` | float | 分解焓 |

### 3. elasticity/ — 弹性性质（225 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `elastic_tensor` | list[list] | 弹性张量（6×6 Voigt 表示） |
| `compliance_tensor` | list[list] | 柔量张量 |
| `bulk_modulus` | dict | 体变模量（Voigt/Reuss/Hill 近似） |
| `shear_modulus` | dict | 剪切模量 |
| `youngs_modulus` | dict | 杨氏模量 |
| `poissons_ratio` | dict | 泊松比 |
| `debye_temperature` | float | 德拜温度（K） |
| `elastic_anisotropy` | float | 弹性各向异性 |
| `k_vrh` | float | 体变模量 VRH 平均（GPa） |
| `g_vrh` | float | 剪切模量 VRH 平均（GPa） |

### 4. dielectric/ — 介电性质（548 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | list[list] | 总介电张量（3×3） |
| `ionic` | list[list] | 离子贡献介电张量 |
| `electronic` | list[list] | 电子贡献介电张量 |
| `e_total` | float | 总介电常数（标量平均） |
| `e_ionic` | float | 离子介电常数 |
| `e_electronic` | float | 电子介电常数 |
| `n` | float | 折射率 |
| `band_gap` | float | 带隙 |
| `poly_e_total` | float | 多晶平均总介电常数 |

### 5. piezoelectric/ — 压电性质（240 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | list | 总压电张量（6 分量 Voigt） |
| `ionic` | list | 离子贡献 |
| `electronic` | list | 电子贡献 |
| `e_ij_max` | float | 最大压电系数 |
| `max_direction` | list | 最大方向向量 |

### 6. magnetism/ — 磁性性质（8253 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `ordering` | str | 磁有序类型（FM/AFM/NM/FiM） |
| `is_magnetic` | bool | 是否磁性 |
| `total_magnetization` | float | 总磁化强度（μB） |
| `total_magnetization_normalized_vol` | float | 体积归一化磁化强度 |
| `total_magnetization_normalized_formula_units` | float | 归一化磁化强度 |
| `num_magnetic_sites` | int | 磁性位点数 |
| `magmoms` | list | 各原子磁矩 |
| `exchange_symmetry` | dict | 交换对称性 |
| `source` | str | 数据来源 |

### 7. oxidation_states/ — 氧化态（8253 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `possible_species` | dict | 各元素可能的氧化态种类（如 Na: [Na1+]） |
| `average_oxidation_states` | dict | 平均氧化态 |
| `method` | str | 分析方法（BVA — Bond Valence Analysis） |

### 8. chemenv/ — 配位化学环境（8253 个 JSON）

注意：部分材料可能检测不到键合关系，部分字段为空。

| 字段 | 类型 | 说明 |
|------|------|------|
| `chemenv_symbol` | str | 化学环境符号（如 O:6） |
| `iupac` | str | IUPAC 配位命名 |
| `iucr` | str | IUCr 表示 |
| `name` | str | 配位多面体名称（如 octahedron） |
| `csm` | float | 连续对称性度量（越小越接近理想几何） |
| `wyckoff_positions` | dict | Wyckoff 位置信息 |

### 9. provenance/ — 来源信息（6144 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `created_at` | str | 创建时间 |
| `references` | list[dict] | 参考文献（DOI, 标题, 作者等） |
| `authors` | list[str] | 作者列表 |
| `history` | list[dict] | 数据历史记录 |
| `remarks` | list[str] | 备注 |
| `tags` | list[str] | 标签 |
| `databases` | list[str] | 来源数据库 |

### 10. bonds/ — 键信息（8253 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `method` | str | 分析方法（CrystalNN） |
| `bond_types` | dict | 各键类型及其统计 |
| `bond_length_stats` | dict | 键长统计（均值、标准差、最小值、最大值） |
| `coordination_envs` | list | 各原子的配位环境 |
| `nearest_neighbors` | list | 最近邻原子信息 |

### 11. absorption/ — 光吸收谱（74 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `energies` | list[float] | 能量坐标（eV） |
| `absorption_coefficient` | list[float] | 吸收系数 |
| `average_imaginary_dielectric` | list[float] | 平均虚部介电函数 |
| `average_real_dielectric` | list[float] | 平均实部介电函数 |
| `bandgap` | float | 计算带隙 |

### 12. robocrys/ — 晶体学自然语言描述（3685 个 JSON）

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | str | 材料的自然语言描述（英文） |
| `condensed_structure` | dict | 精简结构信息（矿物名、维度、化学式等） |

### 13. surface_properties/ — 表面性质

无数据 JSON。只有 `_status.json`，所有材料状态为 `"empty"`。

### 14. grain_boundaries/ — 晶界

无数据 JSON。只有 `_status.json`，所有材料状态为 `"empty"`。

## 公用辅助文件

| 文件 | 说明 |
|------|------|
| `index.csv` | 各端点下载状态全局索引（material_id, formula_pretty, 各端点状态） |
| `_status.json` | 每个端点目录下有一个，记录该端点的下载状态（material_id → "ok"/"empty"/"error"） |

## 数据下载来源

数据通过 `download_props.py` 使用 `mp-api` 客户端（MPRester）下载。下载的 API 端点包括：

- **Batch 模式**（按 material_id 分块查询）: summary, thermo, elasticity, dielectric, piezoelectric, magnetism, oxidation_states, chemenv, provenance, bonds, absorption, surface_properties, grain_boundaries
- **By-ID 模式**（逐个查询）: robocrys

## 与上级目录的关联

本目录的数据与以下文件配合使用：

- `cif/na_bandgap_ge1/` — 对应材料的 CIF 结构文件（8257 个）
- `na_poly_distortion_independent_test.csv` — 各材料的 Na 多面体畸变描述符计算结果（8253 行）

两者可通过 `material_id` 关联（CIF 文件名 = `{material_id}.cif`，props JSON 名称 = `{material_id}.json`）。
