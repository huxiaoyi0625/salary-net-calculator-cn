#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按目标“到手 + 公积金账户入账”反推杭州、深圳、上海、北京的税前月薪。

口径：
- 目标收入为年度收入，单位元。
- “到手 + 公积金”= 全年现金到手 + 个人公积金 + 单位公积金。
- 14/15/16 薪 = 12 个月正常工资 + (薪数 - 12) 个月工资作为全年一次性奖金。
- 社保和公积金仅按 12 个月正常工资缴纳，奖金不缴五险一金。
- 默认年终奖使用全年一次性奖金单独计税。该政策目前延续至 2027-12-31。
- 不考虑专项附加扣除、补充公积金、企业年金、商业健康险等额外扣除。

运行示例：
    python main.py 600000
    python main.py --target 600000 --bonus-tax better
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable


MONTHS = 12
STANDARD_DEDUCTION = 60_000.0
FUND_RATES = (0.05, 0.07, 0.12)
PAY_COUNTS = (12, 13, 14, 15, 16)


@dataclass(frozen=True)
class ContributionItem:
    name: str
    rate: float
    base_min: float
    base_max: float
    fixed: float = 0.0

    def amount(self, monthly_salary: float) -> float:
        base = clamp(monthly_salary, self.base_min, self.base_max)
        return base * self.rate + self.fixed


@dataclass(frozen=True)
class CityConfig:
    name: str
    social_items: tuple[ContributionItem, ...]
    fund_base_min: float
    fund_base_max: float
    notes: str


# 2025 社保年度 / 2025 住房公积金年度公开口径。各地每年会调整，更新这里即可。
# 深圳按非深户、职工医保一档估算；北京医保个人含大额医疗互助 3 元/月。
# 主要来源：
# - 年终奖单独计税：财政部 税务总局公告2023年第30号，延续至2027-12-31。
# - 北京：首都之窗/北京住房公积金管理中心 2025 社保、公积金上下限通告。
# - 上海：上海人社 2025 社保上下限；上海住房公积金网 2025 年度基数调整提示。
# - 杭州：浙人社发〔2025〕52号口径；杭公积金〔2025〕21号。
# - 深圳：2025.7-2026.6养老基数、2026医保基数；深圳公积金2025.7-2026.6基数。
CITIES: tuple[CityConfig, ...] = (
    CityConfig(
        name="杭州",
        social_items=(
            ContributionItem("养老", 0.08, 4_986, 25_299),
            ContributionItem("医疗", 0.02, 4_986, 25_299),
            ContributionItem("失业", 0.005, 4_986, 25_299),
        ),
        fund_base_min=2_490,
        fund_base_max=40_694,
        notes="2025社保上限25299；2025公积金上限40694。",
    ),
    CityConfig(
        name="深圳",
        social_items=(
            ContributionItem("养老", 0.08, 4_775, 27_549),
            ContributionItem("医疗一档", 0.02, 6_727, 33_633),
            ContributionItem("失业", 0.002, 2_520, 44_265),
        ),
        fund_base_min=2_520,
        fund_base_max=44_265,
        notes="非深户、医保一档；2025公积金上限44265。",
    ),
    CityConfig(
        name="上海",
        social_items=(
            ContributionItem("养老", 0.08, 7_460, 37_302),
            ContributionItem("医疗", 0.02, 7_460, 37_302),
            ContributionItem("失业", 0.005, 7_460, 37_302),
        ),
        fund_base_min=2_690,
        fund_base_max=36_921,
        notes="2025社保上限37302；2025公积金上限36921。",
    ),
    CityConfig(
        name="北京",
        social_items=(
            ContributionItem("养老", 0.08, 7_162, 35_811),
            ContributionItem("医疗", 0.02, 7_162, 35_811, fixed=3),
            ContributionItem("失业", 0.005, 7_162, 35_811),
        ),
        fund_base_min=2_540,
        fund_base_max=35_811,
        notes="2025社保/公积金上限35811；医保个人另加3元/月。",
    ),
)


COMPREHENSIVE_TAX_BRACKETS = (
    (36_000, 0.03, 0),
    (144_000, 0.10, 2_520),
    (300_000, 0.20, 16_920),
    (420_000, 0.25, 31_920),
    (660_000, 0.30, 52_920),
    (960_000, 0.35, 85_920),
    (float("inf"), 0.45, 181_920),
)

BONUS_TAX_BRACKETS = (
    (3_000, 0.03, 0),
    (12_000, 0.10, 210),
    (25_000, 0.20, 1_410),
    (35_000, 0.25, 2_660),
    (55_000, 0.30, 4_410),
    (80_000, 0.35, 7_160),
    (float("inf"), 0.45, 15_160),
)


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def progressive_tax(taxable_income: float, brackets: Iterable[tuple[float, float, float]]) -> float:
    taxable_income = max(0.0, taxable_income)
    for ceiling, rate, quick_deduction in brackets:
        if taxable_income <= ceiling:
            return taxable_income * rate - quick_deduction
    raise RuntimeError("unreachable")


def bonus_tax_separate(bonus: float) -> float:
    if bonus <= 0:
        return 0.0
    monthly_equivalent = bonus / 12
    for ceiling, rate, quick_deduction in BONUS_TAX_BRACKETS:
        if monthly_equivalent <= ceiling:
            return bonus * rate - quick_deduction
    raise RuntimeError("unreachable")


def employee_social(city: CityConfig, monthly_salary: float) -> float:
    return sum(item.amount(monthly_salary) for item in city.social_items)


def housing_fund(monthly_salary: float, rate: float, city: CityConfig) -> float:
    return clamp(monthly_salary, city.fund_base_min, city.fund_base_max) * rate


def annual_value(monthly_salary: float, pay_count: int, fund_rate: float, city: CityConfig, bonus_tax_mode: str) -> dict[str, float]:
    social = employee_social(city, monthly_salary)
    fund_personal = housing_fund(monthly_salary, fund_rate, city)
    fund_company = fund_personal
    bonus = monthly_salary * (pay_count - MONTHS)

    regular_taxable = MONTHS * (monthly_salary - social - fund_personal) - STANDARD_DEDUCTION
    regular_tax = progressive_tax(regular_taxable, COMPREHENSIVE_TAX_BRACKETS)

    separate_bonus_tax = bonus_tax_separate(bonus)
    merged_taxable = regular_taxable + bonus
    merged_total_tax = progressive_tax(merged_taxable, COMPREHENSIVE_TAX_BRACKETS)
    merged_bonus_tax = max(0.0, merged_total_tax - regular_tax)

    if bonus_tax_mode == "merge":
        bonus_tax = merged_bonus_tax
    elif bonus_tax_mode == "better":
        bonus_tax = min(separate_bonus_tax, merged_bonus_tax)
    else:
        bonus_tax = separate_bonus_tax

    total_gross = monthly_salary * pay_count
    cash_take_home = total_gross - MONTHS * social - MONTHS * fund_personal - regular_tax - bonus_tax
    total_fund_credit = MONTHS * (fund_personal + fund_company)
    value = cash_take_home + total_fund_credit

    return {
        "monthly_salary": monthly_salary,
        "total_gross": total_gross,
        "cash_take_home": cash_take_home,
        "fund_credit": total_fund_credit,
        "value": value,
        "regular_tax": regular_tax,
        "bonus_tax": bonus_tax,
        "monthly_social": social,
        "monthly_fund_personal": fund_personal,
    }


def solve_monthly_salary(target: float, pay_count: int, fund_rate: float, city: CityConfig, bonus_tax_mode: str) -> dict[str, float]:
    low = 0.0
    high = max(target, 10_000.0)

    while annual_value(high, pay_count, fund_rate, city, bonus_tax_mode)["value"] < target:
        high *= 2
        if high > 10_000_000:
            raise ValueError("目标收入过高，无法在合理范围内求解。")

    for _ in range(80):
        mid = (low + high) / 2
        if annual_value(mid, pay_count, fund_rate, city, bonus_tax_mode)["value"] >= target:
            high = mid
        else:
            low = mid

    return annual_value(high, pay_count, fund_rate, city, bonus_tax_mode)


def money(value: float) -> str:
    return f"{value:,.0f}"


def print_table(city: CityConfig, target: float, bonus_tax_mode: str, verbose: bool) -> None:
    print(f"\n## {city.name}")
    print(f"{city.notes}")
    print("| 薪数 \\ 公积金 | 5% | 7% | 12% |")
    print("|---|---:|---:|---:|")
    for pay_count in PAY_COUNTS:
        cells = []
        for fund_rate in FUND_RATES:
            result = solve_monthly_salary(target, pay_count, fund_rate, city, bonus_tax_mode)
            cells.append(money(result["monthly_salary"]))
        print(f"| {pay_count}薪 | " + " | ".join(cells) + " |")

    if verbose:
        print("\n明细示例：")
        for pay_count in PAY_COUNTS:
            for fund_rate in FUND_RATES:
                result = solve_monthly_salary(target, pay_count, fund_rate, city, bonus_tax_mode)
                print(
                    f"- {pay_count}薪/{fund_rate:.0%}: 月薪 {money(result['monthly_salary'])}, "
                    f"现金到手 {money(result['cash_take_home'])}, "
                    f"公积金入账 {money(result['fund_credit'])}, "
                    f"个税 {money(result['regular_tax'] + result['bonus_tax'])}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="反推四城达到目标年度“到手+公积金”的税前月薪。")
    parser.add_argument("target_pos", nargs="?", type=float, help="目标年度到手+公积金收入，单位元。")
    parser.add_argument("--target", type=float, help="目标年度到手+公积金收入，单位元。")
    parser.add_argument(
        "--bonus-tax",
        choices=("separate", "merge", "better"),
        default="separate",
        help="年终奖计税方式：separate=单独计税，merge=并入综合所得，better=两者取税少者。",
    )
    parser.add_argument("--verbose", action="store_true", help="输出现金到手、公积金和个税明细。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = args.target if args.target is not None else args.target_pos
    if target is None:
        target = float(input("请输入目标年度到手+公积金收入（元）：").replace(",", "").strip())
    if target <= 0:
        raise SystemExit("目标收入必须大于 0。")

    print(f"目标年度到手+公积金：{money(target)} 元")
    print(f"年终奖计税：{args.bonus_tax}")
    print("表格单元格为反推得到的税前月薪，单位元。")
    for city in CITIES:
        print_table(city, target, args.bonus_tax, args.verbose)


if __name__ == "__main__":
    main()
