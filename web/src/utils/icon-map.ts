/**
 * Element Plus 图标映射工具
 * 将图标名称字符串映射为实际的图标组件
 * 使用 markRaw 避免 Vue 响应式开销
 */
import { markRaw } from 'vue'
import {
  // 基础图标
  Odometer,
  ChatDotSquare,
  Setting,
  MagicStick,
  Connection,
  Tools,
  Plus,
  Expand,
  Fold,
  DataLine,
  // 文档图标
  Document,
  Files,
  Folder,
  FolderOpened,
  // 编辑图标
  Edit,
  Delete,
  CopyDocument,
  // 位置图标
  Location,
  LocationInformation,
  // 箭头图标
  ArrowUp,
  ArrowRight,
  ArrowDown,
  ArrowLeft,
  ArrowLeftBold,
  ArrowRightBold,
  // 用户图标
  User,
  UserFilled,
  // 搜索图标
  Search,
  // 提示图标
  Warning,
  WarningFilled,
  InfoFilled,
  CircleCheckFilled,
  CircleCloseFilled,
  // 操作图标
  Refresh,
  List,
  Operation,
  // 菜单图标
  Menu,
  // 加载图标
  Loading,
  // 更多图标
  More,
  // 标签图标
  PriceTag,
  StarFilled,
  // 分享图标
  Share,
  // 下载图标
  Download,
  Link,
  Bell,
  Star,
  // 客服图标
  Service,
  // 电话图标
  Phone,
  // 邮件图标
  Message,
  // 位置图标
  Place,
  // 图表图标
  TrendCharts,
  PieChart,
  DataAnalysis,
  // 锁图标
  Lock,
  Unlock,
  // 相机图标
  Camera,
  // 视频图标
  VideoCamera,
  // 购物车图标
  ShoppingCart,
  ShoppingBag,
  // 阅读图标
  Reading,
  Notebook,
  // 读写
  Clock,
  Calendar,
  AlarmClock,
  Timer,
  // 箭头
  DArrowLeft,
  DArrowRight,
} from '@element-plus/icons-vue'

/**
 * Element Plus 图标映射表
 * key: 图标名称（与路由 meta.icon 对应，使用 Element Plus 组件名）
 * value: 图标组件（使用 markRaw 避免响应式开销）
 */
export const iconMap: Record<string, any> = {
  // 基础/首页
  Odometer: markRaw(Odometer),
  DataLine: markRaw(DataLine),
  Dashboard: markRaw(Odometer),

  // 对话/聊天
  ChatDotSquare: markRaw(ChatDotSquare),
  Message: markRaw(Message),
  Chat: markRaw(ChatDotSquare),

  // Agent/设置
  Setting: markRaw(Setting),
  Agent: markRaw(Setting),
  Agents: markRaw(Setting),

  // 技能/魔法
  MagicStick: markRaw(MagicStick),
  Skill: markRaw(MagicStick),
  Skills: markRaw(MagicStick),

  // 工作流/连接
  Connection: markRaw(Connection),
  Workflow: markRaw(Connection),
  Workflows: markRaw(Connection),

  // 自动化/工具
  Tools: markRaw(Tools),
  Automation: markRaw(Tools),
  Tool: markRaw(Tools),

  // 文档/文件
  Document: markRaw(Document),
  File: markRaw(Document),
  Files: markRaw(Files),
  Folder: markRaw(Folder),
  FolderOpened: markRaw(FolderOpened),

  // 编辑
  Edit: markRaw(Edit),
  Delete: markRaw(Delete),
  CopyDocument: markRaw(CopyDocument),

  // 用户
  User: markRaw(User),
  UserFilled: markRaw(UserFilled),

  // 搜索
  Search: markRaw(Search),

  // 提示/警告
  Warning: markRaw(Warning),
  WarningFilled: markRaw(WarningFilled),
  InfoFilled: markRaw(InfoFilled),
  CircleCheckFilled: markRaw(CircleCheckFilled),
  CircleCloseFilled: markRaw(CircleCloseFilled),

  // 操作
  Refresh: markRaw(Refresh),
  Operation: markRaw(Operation),
  List: markRaw(List),

  // 菜单
  Menu: markRaw(Menu),

  // 加载
  Loading: markRaw(Loading),

  // 更多
  More: markRaw(More),

  // 标签
  PriceTag: markRaw(PriceTag),

  // 收藏
  Star: markRaw(Star),
  StarFilled: markRaw(StarFilled),

  // 分享
  Share: markRaw(Share),

  // 上传下载
  Download: markRaw(Download),

  // 链接
  Link: markRaw(Link),

  // 通知
  Bell: markRaw(Bell),

  // 图表
  TrendCharts: markRaw(TrendCharts),
  PieChart: markRaw(PieChart),
  DataAnalysis: markRaw(DataAnalysis),

  // 锁
  Lock: markRaw(Lock),
  Unlock: markRaw(Unlock),


  // 位置
  Location: markRaw(Location),
  Place: markRaw(Place),
  LocationInformation: markRaw(LocationInformation),

  // 箭头
  ArrowUp: markRaw(ArrowUp),
  ArrowRight: markRaw(ArrowRight),
  ArrowDown: markRaw(ArrowDown),
  ArrowLeft: markRaw(ArrowLeft),
  ArrowLeftBold: markRaw(ArrowLeftBold),
  ArrowRightBold: markRaw(ArrowRightBold),
  DArrowLeft: markRaw(DArrowLeft),
  DArrowRight: markRaw(DArrowRight),

  // 相机
  Camera: markRaw(Camera),

  // 视频
  VideoCamera: markRaw(VideoCamera),

  // 购物
  ShoppingCart: markRaw(ShoppingCart),
  ShoppingBag: markRaw(ShoppingBag),

  // 阅读
  Reading: markRaw(Reading),
  Notebook: markRaw(Notebook),

  // 时间
  Clock: markRaw(Clock),
  AlarmClock: markRaw(AlarmClock),
  Timer: markRaw(Timer),

  // 日历
  Calendar: markRaw(Calendar),

  // 电话
  Phone: markRaw(Phone),

  // 服务
  Service: markRaw(Service),

  // Plus
  Plus: markRaw(Plus),
  // Fold
  Fold: markRaw(Fold),
  // Expand
  Expand: markRaw(Expand),
}

/**
 * 根据图标名称获取图标组件
 * @param iconName 图标名称（Element Plus 组件名）
 * @returns 图标组件，如果不存在则返回默认图标
 */
export function getIconByName(iconName: string): any {
  return iconMap[iconName] || iconMap.Setting
}
