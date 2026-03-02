"""
技能初始化管理器

负责在应用启动时初始化所有技能
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_data_gen.infra.db.sample_repository import SampleRepository
    from api_data_gen.infra.db.schema_repository import SchemaRepository
    from api_data_gen.services.interface_trace_service import InterfaceTraceService
    from api_data_gen.services.schema_service import SchemaService
    from api_data_gen.services.ai_scenario_service import AiScenarioService
    from api_data_gen.services.ai_data_generation_service import AiDataGenerationService
    from api_data_gen.services.ai_data_analysis_service import AiDataAnalysisService
    from api_data_gen.services.local_field_rule_service import LocalFieldRuleService


class SkillManager:
    """
    技能管理器

    负责初始化和管理所有技能
    """

    _initialized = False

    @classmethod
    def initialize(
        cls,
        sample_repository: "SampleRepository" = None,
        schema_repository: "SchemaRepository" = None,
        interface_trace_service: "InterfaceTraceService" = None,
        schema_service: "SchemaService" = None,
        ai_scenario_service: "AiScenarioService" = None,
        ai_data_generation_service: "AiDataGenerationService" = None,
        ai_data_analysis_service: "AiDataAnalysisService" = None,
        local_field_rule_service: "LocalFieldRuleService" = None,
    ) -> None:
        """
        初始化所有技能

        :param sample_repository: 样本数据仓库
        :param schema_repository: 表结构仓库
        :param interface_trace_service: 接口追踪服务
        :param schema_service: 表结构服务
        :param ai_scenario_service: AI 场景生成服务
        :param ai_data_generation_service: AI 数据生成服务
        :param ai_data_analysis_service: AI 数据分析服务
        :param local_field_rule_service: 本地字段规则服务
        """
        # 导入并初始化各个技能模块
        from .data_sampling import init_skills as init_data_skills
        from .scenario_skills import init_skills as init_scenario_skills
        from .data_generation import init_skills as init_generation_skills
        from .interface_skills import init_skills as init_interface_skills

        # 初始化数据采样技能
        init_data_skills(
            sample_repository=sample_repository,
            schema_repository=schema_repository,
            interface_trace_service=interface_trace_service,
            schema_service=schema_service,
        )

        # 初始化场景生成技能
        init_scenario_skills(
            ai_scenario_service=ai_scenario_service,
            ai_data_generation_service=ai_data_generation_service,
            local_field_rule_service=local_field_rule_service,
        )

        # 初始化数据生成技能
        init_generation_skills(
            ai_data_generation_service=ai_data_generation_service,
            ai_data_analysis_service=ai_data_analysis_service,
            local_field_rule_service=local_field_rule_service,
        )

        # 初始化接口和 Schema 技能
        init_interface_skills(
            interface_trace_service=interface_trace_service,
            schema_service=schema_service,
            schema_repository=schema_repository,
        )

        cls._initialized = True

    @classmethod
    def is_initialized(cls) -> bool:
        """检查是否已初始化"""
        return cls._initialized

    @classmethod
    def reset(cls) -> None:
        """重置初始化状态（主要用于测试）"""
        cls._initialized = False


def get_skill_manager() -> SkillManager:
    """获取技能管理器实例"""
    return SkillManager
