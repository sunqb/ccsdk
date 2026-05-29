"""
WeChat Bot 指标埋点模块

负责：
- OpenTelemetry 指标埋点
- 消息数、错误数、耗时、活跃任务等可观测性指标
- 对齐现有 RAG observability 风格
"""
import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WeChatBotMetrics:
    """
    微信机器人指标收集器

    提供消息处理的可观测性指标：
    - 消息数（总数、按类型分类）
    - 错误数（按错误类型分类）
    - 处理耗时（延迟）
    - 活跃任务数
    - 限流触发次数
    """

    def __init__(self):
        self._enabled = settings.wechatbot_otel_enabled
        self._initialized = False
        self._metrics = None
        self._meter = None
        self._messages_received_counter = None
        self._messages_active_counter = None
        self._messages_completed_counter = None
        self._processing_time_histogram = None
        self._errors_counter = None
        self._rate_limit_counter = None
        self._media_handled_counter = None

        if self._enabled:
            self._init_otel()

    def _init_otel(self) -> None:
        """初始化 OpenTelemetry"""
        try:
            from opentelemetry import metrics
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            # 创建资源
            resource = Resource.create({
                "service.name": "wechatbot",
                "service.version": "1.0.0",
            })

            # 创建 OTLP 导出器
            otlp_endpoint = settings.wechatbot_otel_endpoint
            if otlp_endpoint:
                exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)

                # 创建 MeterProvider
                reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
                provider = MeterProvider(resource=resource, metric_readers=[reader])

                # 设置全局 provider
                metrics.set_meter_provider(provider)

                # 获取 Meter
                self._meter = metrics.get_meter("wechatbot", "1.0.0")
                self._messages_received_counter = self._meter.create_counter(
                    name="wechatbot.messages.received",
                    description="收到的微信消息数",
                    unit="1",
                )
                self._messages_active_counter = self._meter.create_up_down_counter(
                    name="wechatbot.messages.active",
                    description="当前活跃消息处理数",
                    unit="1",
                )
                self._messages_completed_counter = self._meter.create_counter(
                    name="wechatbot.messages.completed",
                    description="完成的微信消息数",
                    unit="1",
                )
                self._processing_time_histogram = self._meter.create_histogram(
                    name="wechatbot.messages.processing_time",
                    description="消息处理耗时",
                    unit="ms",
                )
                self._errors_counter = self._meter.create_counter(
                    name="wechatbot.errors",
                    description="错误计数",
                    unit="1",
                )
                self._rate_limit_counter = self._meter.create_counter(
                    name="wechatbot.rate_limit.exceeded",
                    description="限流触发次数",
                    unit="1",
                )
                self._media_handled_counter = self._meter.create_counter(
                    name="wechatbot.media.handled",
                    description="处理的媒体消息数",
                    unit="1",
                )
                self._initialized = True

                logger.info(f"OpenTelemetry 指标已初始化，导出到 {otlp_endpoint}")
            else:
                logger.warning("OpenTelemetry endpoint 未配置，指标功能不可用")

        except ImportError:
            logger.warning(
                "opentelemetry 包未安装，指标功能不可用。"
                "请运行: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
            )
        except Exception as e:
            logger.warning(f"OpenTelemetry 初始化失败: {e}")

    def _ensure_initialized(self) -> bool:
        """确保已初始化"""
        if not self._enabled:
            return False

        if not self._initialized:
            self._init_otel()

        return self._initialized

    def _ensure_instruments(self) -> bool:
        return bool(
            self._messages_received_counter
            and self._messages_active_counter
            and self._messages_completed_counter
            and self._processing_time_histogram
            and self._errors_counter
            and self._rate_limit_counter
            and self._media_handled_counter
        )

    def record_message_received(self, message_type: str = "text") -> None:
        """
        记录收到消息

        Args:
            message_type: 消息类型
        """
        if not self._ensure_initialized():
            return

        try:
            if not self._ensure_instruments():
                return
            self._messages_received_counter.add(1, {"message_type": message_type})
            self._messages_active_counter.add(1, {"message_type": message_type})

        except Exception as e:
            logger.warning(f"指标记录失败: {e}")

    def record_message_completed(
        self,
        message_type: str = "text",
        processing_time_ms: float = 0.0,
        success: bool = True,
    ) -> None:
        """
        记录消息处理完成

        Args:
            message_type: 消息类型
            processing_time_ms: 处理耗时（毫秒）
            success: 是否成功
        """
        if not self._ensure_initialized():
            return

        try:
            if not self._ensure_instruments():
                return
            self._messages_active_counter.add(-1, {"message_type": message_type})
            result = "success" if success else "failure"
            self._messages_completed_counter.add(1, {"message_type": message_type, "result": result})
            self._processing_time_histogram.record(processing_time_ms, {"message_type": message_type})

        except Exception as e:
            logger.warning(f"指标记录失败: {e}")

    def record_error(
        self,
        error_type: str,
        message_type: str = "text",
    ) -> None:
        """
        记录错误

        Args:
            error_type: 错误类型
            message_type: 消息类型
        """
        if not self._ensure_initialized():
            return

        try:
            if not self._ensure_instruments():
                return
            self._errors_counter.add(1, {"error_type": error_type, "message_type": message_type})

        except Exception as e:
            logger.warning(f"指标记录失败: {e}")

    def record_rate_limit(self, user_id_hash: str) -> None:
        """
        记录限流触发

        Args:
            user_id_hash: 用户 ID 哈希
        """
        if not self._ensure_initialized():
            return

        try:
            if not self._ensure_instruments():
                return
            self._rate_limit_counter.add(1, {"user_id_hash": user_id_hash[:8]})

        except Exception as e:
            logger.warning(f"指标记录失败: {e}")

    def record_media_handled(
        self,
        message_type: str,
        policy: str,
        success: bool = True,
    ) -> None:
        """
        记录媒体消息处理

        Args:
            message_type: 媒体类型
            policy: 处理的策略
            success: 是否成功
        """
        if not self._ensure_initialized():
            return

        try:
            if not self._ensure_instruments():
                return
            result = "success" if success else "failure"
            self._media_handled_counter.add(1, {"media_type": message_type, "policy": policy, "result": result})

        except Exception as e:
            logger.warning(f"指标记录失败: {e}")


# 全局单例
_wechatbot_metrics: WeChatBotMetrics | None = None


def get_wechatbot_metrics() -> WeChatBotMetrics:
    """获取全局指标收集器"""
    global _wechatbot_metrics
    if _wechatbot_metrics is None:
        _wechatbot_metrics = WeChatBotMetrics()
    return _wechatbot_metrics
