#!/usr/bin/env python3
"""Create idempotent, module-organized test cases for the mind-map workbench."""

from datetime import datetime, timezone
from pathlib import Path
import sys


sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import crud, schemas  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Project, TestCase, TestCaseSection, TestSuite  # noqa: E402


SUITE_NAME = "电商全链路回归（脑图演示）"

MODULES = [
    ("01 账号与权限", [
        ("注册与登录", [
            ("手机号验证码注册成功", "high", "未注册手机号可正常接收短信", "输入正确手机号和验证码", "账号创建成功并自动登录"),
            ("密码连续错误触发账号保护", "critical", "账号已设置登录密码", "连续输入错误密码 5 次", "账号临时锁定并提示剩余锁定时间"),
            ("登录会话过期后安全跳转", "high", "用户已登录且会话即将过期", "等待会话过期后访问个人中心", "跳转登录页且不泄露原页面数据"),
        ]),
        ("角色与权限", [
            ("普通用户不可访问管理后台", "critical", "普通用户账号已登录", "直接访问后台管理地址", "返回无权限提示且不展示管理数据"),
            ("管理员角色变更即时生效", "high", "目标用户当前为普通用户", "管理员授予运营角色后刷新页面", "用户获得对应菜单和操作权限"),
            ("跨租户资源访问被拒绝", "critical", "存在两个相互隔离的租户", "租户 A 用户请求租户 B 资源", "服务端拒绝请求并记录安全审计"),
        ]),
    ]),
    ("02 商品中心", [
        ("商品搜索", [
            ("按关键词搜索在售商品", "medium", "存在名称包含关键词的在售商品", "搜索商品关键词并提交", "结果仅展示匹配且可售的商品"),
            ("无结果搜索展示友好空状态", "low", "搜索词没有任何匹配商品", "提交不存在的商品关键词", "展示空状态和推荐入口"),
            ("特殊字符搜索不触发异常", "high", "商品搜索服务可用", "输入引号、百分号和脚本片段", "请求被安全处理且页面正常返回"),
        ]),
        ("库存与详情", [
            ("商品详情展示实时库存", "high", "商品存在多个 SKU 且库存不同", "切换颜色和尺码规格", "库存和购买状态随 SKU 正确变化"),
            ("库存为零时禁止加入购物车", "high", "目标 SKU 库存为 0", "点击加入购物车", "按钮不可用并提示到货通知"),
            ("商品下架后旧链接不可购买", "critical", "用户保留已下架商品详情链接", "打开旧链接并尝试购买", "显示下架状态且无法创建订单"),
        ]),
    ]),
    ("03 购物车", [
        ("商品操作", [
            ("同一 SKU 重复加入合并数量", "medium", "购物车中已有目标 SKU 1 件", "再次加入相同 SKU 2 件", "购物车合并为同一行且数量为 3"),
            ("购物车数量不能超过库存", "high", "目标 SKU 库存为 5", "将购物车数量修改为 6", "数量保持在 5 并提示库存不足"),
            ("删除商品后金额实时重算", "high", "购物车中有两种商品", "删除其中一种商品", "商品移除且总价、优惠同步更新"),
        ]),
        ("优惠计算", [
            ("满减与店铺券按规则叠加", "critical", "订单同时满足满减和店铺券条件", "勾选商品并选择可用优惠券", "优惠顺序和应付金额符合活动规则"),
            ("优惠券过期后自动失效", "high", "购物车已选择即将过期的优惠券", "等待优惠券过期后进入结算", "优惠券取消选中且金额恢复"),
            ("凑单商品取消后撤销满减", "high", "购物车刚好满足满减门槛", "取消勾选一件凑单商品", "满减失效且应付金额正确重算"),
        ]),
    ]),
    ("04 订单履约", [
        ("下单结算", [
            ("库存充足时提交订单成功", "critical", "购物车商品可售且地址有效", "确认订单信息并提交", "生成唯一订单号并锁定库存"),
            ("重复点击提交只生成一张订单", "critical", "结算页订单信息有效", "快速连续点击提交订单", "幂等处理且只生成一张订单"),
            ("提交时库存变化给出明确提示", "critical", "结算期间其他用户买完最后库存", "提交当前订单", "订单不创建并提示失效商品"),
        ]),
        ("物流状态", [
            ("发货后展示物流轨迹", "medium", "订单已发货且有物流单号", "打开订单物流详情", "按时间倒序展示承运商轨迹"),
            ("签收状态同步订单完成", "high", "物流平台已回传签收", "刷新订单详情", "物流显示已签收且订单进入完成状态"),
            ("异常物流支持联系客服", "medium", "物流轨迹超过 72 小时未更新", "查看物流异常提醒", "显示异常说明和客服入口"),
        ]),
    ]),
    ("05 支付中心", [
        ("支付流程", [
            ("微信支付成功回写订单", "critical", "待支付订单金额有效", "选择微信支付并完成付款", "订单变为已支付且支付流水可查询"),
            ("支付取消后订单保持待支付", "high", "订单处于待支付状态", "唤起支付后主动取消", "订单仍可再次支付且无重复流水"),
            ("支付回调重复到达保持幂等", "critical", "支付平台已产生成功回调", "重复发送同一支付回调", "仅记账一次且订单状态不重复流转"),
        ]),
        ("退款对账", [
            ("全额退款原路退回", "critical", "已支付订单允许退款", "发起全额退款并等待处理", "退款金额原路返回且生成退款流水"),
            ("部分退款不超过实付金额", "high", "订单包含多件可退商品", "多次申请部分退款", "累计退款不超过订单实付金额"),
            ("日终对账差异进入待处理", "high", "存在支付平台与本地金额不一致流水", "执行日终自动对账", "差异单被标记并进入人工处理队列"),
        ]),
    ]),
    ("06 售后与客服", [
        ("退换货", [
            ("签收后七天内申请退货", "high", "订单已签收且仍在退货期限内", "选择商品并提交退货原因", "生成售后单并展示寄回指引"),
            ("超期退货申请被正确拦截", "medium", "订单已超过无理由退货期限", "提交无质量问题退货申请", "申请被拦截并说明不支持原因"),
            ("换货完成后关联新物流单", "high", "换货申请已审核通过", "仓库发出替换商品", "售后详情展示新的物流单和进度"),
        ]),
        ("客服工单", [
            ("订单问题自动关联客服工单", "medium", "用户从订单详情发起咨询", "填写问题并提交客服请求", "工单自动关联用户和订单信息"),
            ("敏感信息在客服视图脱敏", "critical", "工单包含手机号和收货地址", "客服打开工单详情", "敏感字段按权限脱敏展示"),
            ("工单关闭后用户评价生效", "low", "客服已解决并关闭工单", "用户提交满意度和文字评价", "评价保存且不可重复提交"),
        ]),
    ]),
]


def main() -> None:
    db = SessionLocal()
    try:
        project = db.query(Project).order_by(Project.id).first()
        if project is None:
            raise RuntimeError("No project exists; finish initial setup first")

        suite = db.query(TestSuite).filter(
            TestSuite.project_id == project.id,
            TestSuite.name == SUITE_NAME,
        ).first()
        if suite is None:
            suite = TestSuite(
                name=SUITE_NAME,
                description="用于验证脑图目录、字段节点和结构化步骤的真实电商场景数据",
                project_id=project.id,
                status="ACTIVE",
            )
            db.add(suite)
            db.commit()
            db.refresh(suite)

        created_sections = 0
        created_cases = 0
        for module_index, (module_name, groups) in enumerate(MODULES, start=1):
            module = db.query(TestCaseSection).filter(
                TestCaseSection.test_suite_id == suite.id,
                TestCaseSection.parent_section_id.is_(None),
                TestCaseSection.name == module_name,
            ).first()
            if module is None:
                module = TestCaseSection(
                    name=module_name,
                    description=f"{module_name}相关回归场景",
                    test_suite_id=suite.id,
                    order_index=module_index,
                )
                db.add(module)
                db.commit()
                db.refresh(module)
                created_sections += 1

            for group_index, (group_name, cases) in enumerate(groups, start=1):
                group = db.query(TestCaseSection).filter(
                    TestCaseSection.test_suite_id == suite.id,
                    TestCaseSection.parent_section_id == module.id,
                    TestCaseSection.name == group_name,
                ).first()
                if group is None:
                    group = TestCaseSection(
                        name=group_name,
                        description=f"{module_name} / {group_name}",
                        test_suite_id=suite.id,
                        parent_section_id=module.id,
                        order_index=group_index,
                    )
                    db.add(group)
                    db.commit()
                    db.refresh(group)
                    created_sections += 1

                for case_index, (title, priority, precondition, action, expected) in enumerate(cases, start=1):
                    exists = db.query(TestCase.id).filter(
                        TestCase.test_suite_id == suite.id,
                        TestCase.title == title,
                    ).first()
                    if exists:
                        continue
                    payload = schemas.TestCaseCreate(
                        title=title,
                        description=f"验证{module_name.replace(module_name[:3], '')}中“{group_name}”场景：{title}。",
                        test_type="manual",
                        preconditions=precondition,
                        priority=priority,
                        status="active",
                        test_suite_id=suite.id,
                        section_id=group.id,
                        order_index=case_index,
                        is_multistep=True,
                        test_steps=[
                            schemas.TestCaseStepCreate(step_number=1, order_index=1, action="准备测试数据并确认前置条件", expected_result=precondition),
                            schemas.TestCaseStepCreate(step_number=2, order_index=2, action=action, expected_result=expected),
                            schemas.TestCaseStepCreate(step_number=3, order_index=3, action="刷新页面并重新查询服务端记录", expected_result="页面与服务端数据一致，且没有产生重复记录"),
                        ],
                    )
                    crud.create_test_case(db, payload, created_by=project.owner_id)
                    created_cases += 1

        print(
            f"project={project.name!r} suite_id={suite.id} suite={suite.name!r} "
            f"created_sections={created_sections} created_cases={created_cases}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
