# Design Document — Nootbook 作品集 PPT

## 1. Profile Baseline Declaration

- **Profile selection**: `profiles/general.md`
- **Selection rationale**: 这是一个个人作品集项目展示，面向技术面试官或潜在合作方，需要专业清晰但不过于商务化
- **Referenced dimensions**: 信息密度（中高）、内容表达技巧（KPI大数字、结构化列表）、字体层级指导
- **Deviation notes**: 
  - 偏离通用商务风格，采用深色科技风格（更契合 AI/技术项目属性）
  - 增加产品截图占位区域（作品集特有需求）
  - 封面和章节页采用 Hero 设计（全幅背景图+渐变遮罩）

## 2. Style Baseline Declaration

- **Style anchor selection**: 
  - **Apple WWDC 风格**：深色背景 + 高饱和度强调色 + 大字体标题，参考其技术产品发布会的视觉冲击力
  - **Vercel 设计系统**：深色主题 + 简洁几何 + 精准间距，参考其开发者产品的专业感
- **Referenced dimension explanation**: 
  - 从 Apple 参考：深色背景上的高对比度文字、渐变遮罩的图片处理、大字号标题层级
  - 从 Vercel 参考：技术标签的呈现方式、代码片段的展示风格、信息卡片的极简处理

## 3. Style Details

### Color Design Principles
- **整体色彩倾向**: 偏 striking & bold（作品集需要视觉记忆点）
- **色温**: 冷色调，深蓝灰基底 + 暖色点缀
- **主色**: `#0F172A` — 深蓝灰（Slate 900），作为页面主背景，沉稳有科技感
- **背景色**: `#0F172A` — 与主色一致，保持深色沉浸感
- **文字色**: `#F8FAFC` — 极浅灰白（Slate 50），确保深色背景上的高可读性
- **次要色**: `#334155` — 中灰蓝（Slate 700），用于分割线、次要文字、卡片边框
- **强调色**: `#F59E0B` — 琥珀橙，用于关键数据、标签、高亮，与冷色基底形成对比
- **辅助强调**: `#10B981` — 翠绿，用于成功状态、技术栈标签中的前端标识
- **辅助强调2**: `#3B82F6` — 亮蓝，用于链接、交互元素

### Font Usage Principles
- **中文标题**: `alimamashuheiti` — 几何感强，商业科技感
- **中文正文**: `MiSans` — 清晰现代，屏幕渲染优秀
- **英文标题**: `Liter` — 现代新怪诞风格，低对比，适合科技产品
- **英文正文**: `Liter` — 与标题统一，保持简洁
- **字号层级**:
  - 封面标题: 48px
  - 封面副标题: 22px
  - 章节标题: 40px
  - 页面标题: 28px
  - 正文: 18-20px
  - 辅助文字/标签: 14px
  - 脚注: 12px

### Text Box and Container Styles
- 内容分隔：优先使用留白和字号差异建立层级
- 卡片样式：圆角矩形（roundRect, adjustments: [8000]），细边框（1px, `#334155`），无填充或极浅填充（`#1E293B`）
- 装饰元素：细直线分隔线、小圆点列表标记、左侧色条（4px宽，强调色）

### Image Style
- **图标**: 使用 solid 风格图标（fas），强调色填充，克制使用
- **表格**: 极简风格，深色表头（`#1E293B`），交替行（`#0F172A` / `#1E293B`），细边框
- **图表**: 极简风格，单色系或双色系，去除多余网格线
- **插图**: 封面/章节页使用全幅科技抽象背景图 + 深色渐变遮罩，内容页预留截图占位框

## 4. Layout System

### Global Layout Characteristics
- **页面尺寸**: 1280 x 720 (16:9)
- **页面边距**: 左右 60px，上下 50px
- **统一页面元素**:
  - 底部右侧：页码（14px，次要色）
  - 内容页顶部：页面标题区（标题 + 细分割线）
  - 无固定导航栏/侧边栏

### Special Page Layouts
- **封面**: Hero 设计 — 全幅背景图 + 从下到上的深色渐变遮罩（`#0F172A` 到透明），居中大标题 + 副标题 + 底部标签行
- **目录**: 非对称双栏 — 左侧大字 "CONTENTS" 竖排或倾斜，右侧章节列表带序号和细线分隔
- **章节过渡页**: Hero 设计 — 全幅背景图 + 遮罩，左侧大号章节编号（强调色，60px）+ 章节标题
- **结尾页**: 类似封面，居中感谢文字 + 项目 Slogan

### Content Page Layout Patterns
- **左右分栏**: 左侧文字内容（60%）+ 右侧截图占位（40%），用于功能展示页
- **上下分区**: 顶部标题区 + 中部内容卡片网格（2-3列）
- **全幅代码/架构**: 顶部标题 + 中部大型架构图/代码块（80%宽度居中）
- **截图占位框设计**: 圆角矩形，内部显示 "[产品截图占位]" 提示文字，细虚线边框（`#334155`，dash 样式）

## 5. Style Usage Rules

- `$title`: 封面标题、章节标题 — alimamashuheiti, 48px, 白色
- `$subtitle`: 封面副标题、章节副标题 — MiSans, 22px, 浅灰
- `$heading`: 内容页标题 — alimamashuheiti, 28px, 白色
- `$body`: 正文内容 — MiSans, 18px, 浅灰白，行高 1.6
- `$caption`: 辅助文字、标签、页码 — MiSans, 14px, 中灰蓝
- `$accent_text`: 强调文字、关键数据 — Liter, 20px, 琥珀橙
- `$primary`: 主背景、深色填充
- `$secondary`: 次要文字、分割线、边框
- `$accent`: 强调色，用于标签、高亮、关键数字
- `$text`: 主要文字颜色
- `$card_bg`: 卡片背景色

## 6. Risk Prohibitions

- [ ] 禁止使用蓝色/青色作为主色（避免廉价科技感）
- [ ] 禁止使用白色背景（破坏深色科技氛围）
- [ ] 禁止正文字号低于 18px
- [ ] 禁止辅助文字/标签低于 12px
- [ ] 禁止标题字号低于 26px
- [ ] 禁止截图占位框使用实线边框（必须用虚线以区分真实内容）
- [ ] 禁止左右布局时底部不对齐
- [ ] 禁止内容页出现大面积空白（截图占位区域不算空白）
- [ ] 禁止过度装饰（渐变、阴影滥用）
- [ ] 禁止圆角矩形卡片过多（优先用留白分隔）

## 7. Theme Definition

```yaml
theme:
  colors:
    primary: "#0F172A"
    secondary: "#334155"
    accent: "#F59E0B"
    accent_green: "#10B981"
    accent_blue: "#3B82F6"
    background: "#0F172A"
    text: "#F8FAFC"
    text_secondary: "#94A3B8"
    card_bg: "#1E293B"
    border: "#334155"
  textStyles:
    title:
      fontSize: 48
      color: "$text"
      fontFamily: "Liter, alimamashuheiti"
      letterSpacing: 2
    subtitle:
      fontSize: 22
      color: "$text_secondary"
      fontFamily: "Liter, MiSans"
      lineHeight: 1.5
    heading:
      fontSize: 28
      color: "$text"
      fontFamily: "Liter, alimamashuheiti"
    body:
      fontSize: 18
      color: "$text"
      fontFamily: "Liter, MiSans"
      lineHeight: 1.6
    caption:
      fontSize: 14
      color: "$text_secondary"
      fontFamily: "Liter, MiSans"
    accent_text:
      fontSize: 20
      color: "$accent"
      fontFamily: "Liter, alimamashuheiti"
  tableStyles:
    default:
      fontSize: 16
      fontFamily: "Liter, MiSans"
      headerFill: "$card_bg"
      headerColor: "$text"
      headerBold: true
      bodyFill: ["$primary", "$card_bg"]
      bodyColor: "$text"
      border:
        style: solid
        width: 1
        color: "$border"
```
