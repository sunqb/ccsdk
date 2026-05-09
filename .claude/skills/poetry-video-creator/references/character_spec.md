# 主体形象设计规范

## 输出内容

```markdown
## 核心定位
[一句话锚定人物形象，明确"是什么"和"不是什么"]
示例：中年盛唐诗人，气质狂放不羁，而非少年仙侠男主。

## 详细特征（7维度）

| 维度 | 描述 |
|------|------|
| 年龄气质 | [年龄段 + 核心气质关键词，明确排除气质] |
| 面容 | [脸型/额/眉/须/眼神，具体可视觉化] |
| 体态 | [身形/骨架/姿态特点] |
| 服饰 | [朝代服饰+色系+禁止装饰] |
| 发型 | [束发方式+自然感，禁止仙侠装饰] |
| 标志性动作 | [1-2个最具辨识度的动态姿势] |
| 背景氛围 | [人物常处的环境类型] |

## 色彩与风格
- 主色调：[从style-presets.md对应风格提取]
- 辅助色：
- 画风参考：
- 色彩对比逻辑：[如"人淡景浓，以静衬动"/"人物暖色环境冷色"等画面层次逻辑]

## 色值规范（十六进制）
- 主色1：#XXXXXX
- 主色2：#XXXXXX
- 辅色1：#XXXXXX
- 辅色2：#XXXXXX
- 背景色：#XXXXXX

## 场景互动关系
[人物与画面中其他元素的主次关系，直接指导 image_prompt 的构图]

| 元素 | 处理方式 |
|------|---------|
| [人物A/建筑/自然物] | [画面位置/大小/虚实/是否出现] |
| [人物B] | [如不出现，说明原因；如出现，与主体的关系] |
| [核心环境] | [主次关系：主体/陪衬/背景] |

## 情绪层次（按画面推进）
[同一首诗内，人物表情/姿态随分镜推进的渐变]

| 阶段 | 表情/姿态 | 关键词 |
|------|----------|--------|
| 首帧 | [初始情绪] | [英文prompt词] |
| 中帧 | [情绪变化] | [英文prompt词] |
| 末帧 | [最终情绪] | [英文prompt词] |

## 分场景微调
[同一人物在不同诗词/场景中的形象侧重，至少列出当前诗词的微调]

| 场景/诗词 | 形象侧重 |
|-----------|---------|
| {当前诗词} | [具体微调描述] |
| [其他相关诗词] | [如有已知场景，列出参考] |

## 必须禁止的元素
- ❌ [面容禁止]
- ❌ [装饰禁止]
- ❌ [材质/特效禁止]
- ❌ [表情气质禁止]
- ❌ [背景禁止]
- ❌ [场景级禁止]（如"禁止酒壶（应为酒杯，且未饮）"/"禁止江面其他船只破坏孤帆意境"）

## 一致性关键词
[5-10个关键词]

## AI生成Prompt（英文，可直接复制使用）

### 基础Prompt
[style_prefix] + [7维度描述的英文转写] + [画质词]

### 负面Prompt
通用负向提示词（见style-presets.md） + 风格专属负向约束 + 本角色禁止元素英文转写 + 场景级禁止英文转写

### 风格触发词
[...]

### 角色一致性注入模板
[用于每个分镜的image_prompt中插入角色描述，确保跨分镜一致]

### 情绪变体Prompt片段
[按情绪层次表，提供每个阶段的表情/姿态英文描述，供各分镜的image_prompt选用]
```

## 设计原则

1. **核心定位先行**：必须先有一句话定位（"是X而非Y"），防止AI生成时偏移到仙侠/网红等方向
2. **7维度全覆盖**：年龄气质/面容/体态/服饰/发型/标志性动作/背景氛围，缺一不可
3. **场景互动关系**：明确人物与画面中其他元素的主次，防止喧宾夺主（如黄鹤楼不能抢主体）
4. **情绪层次推进**：同一首诗内人物表情随分镜渐变（如从强笑→蹙眉→怅然），避免各分镜表情雷同
5. **色彩对比逻辑**：不只是列色值，还要说明色彩层次的底层逻辑（如"人淡景浓"）
6. **分场景微调**：同一人物在不同诗词中形象侧重不同（如李白醉态vs送别），需明确当前诗词的微调方向
7. **禁止元素分级**：风格级（style-presets.md）+ 角色级 + 场景级（如"禁止酒壶应为酒杯"）
8. **符合诗词朝代的历史背景**：服饰/器物/发型的朝代准确性
9. **描述具体、可视觉化**：避免"气质儒雅"等抽象词，改为"方正脸型，宽额浓眉，眼神明亮锐利"
10. **必须输出可直接用于AI生成的英文Prompt**

---

## 示例一：李白·豪放型（将进酒等，fantasy-ancient 风格）

```markdown
## 核心定位
中年盛唐诗人，气质狂放不羁，而非少年仙侠男主。

## 详细特征（7维度）

| 维度 | 描述 |
|------|------|
| 年龄气质 | 40-50岁中年，面容有风霜感，非白净少年。神色傲岸、眼带醉意狂态，而非冷峻或温柔 |
| 面容 | 方正脸型，宽额、浓眉、有须髯（三缕长须），古典审美中的"美髯公"。眼神明亮锐利，有"仰天大笑"的神气 |
| 体态 | 身形挺拔但不单薄，宽袍大袖下的文人骨架，举杯时姿态舒展狂放 |
| 服饰 | 唐代文人常服：圆领袍或交领宽袍，色系以白、青、赭石为主，无繁复纹样、无铠甲。腰间系简单丝绦，禁止金色刺绣堆砌 |
| 发型 | 束发戴巾（儒巾或幞头），发丝自然微乱，可有几缕散落显醉后不羁，禁止精致发冠、流苏步摇 |
| 标志性动作 | 一手持酒壶/酒杯（青铜或陶质），一手挥毫或指天，身体微倾，动态感强 |
| 背景氛围 | 黄河、明月、酒楼、山水，水墨或淡彩渲染，大面积留白，突出人物孤独狂放 |

## 色彩对比逻辑
人物暖色（赭石袍+金色光影），环境冷色（墨青山河），以冷衬热，突出人物生命力。

## 场景互动关系

| 元素 | 处理方式 |
|------|---------|
| 酒/酒器 | 人物手持，近景可见，是情绪的延伸 |
| 山河/明月 | 远景留白，不抢主体，仅作意境烘托 |
| 其他人物 | 一般不出现，突出"独"的意境 |

## 情绪层次（以《将进酒》为例）

| 阶段 | 表情/姿态 | 关键词 |
|------|----------|--------|
| 首帧 | 举杯豪迈，仰头欲饮 | looking up proudly, wine cup raised high |
| 中帧 | 醉态渐浓，笑中带悲 | half-drunk, wild laugh mixed with sorrow |
| 末帧 | 凝视远方，悲凉沉郁 | gazing afar, melancholy beneath bravado |

## 分场景微调

| 场景/诗词 | 形象侧重 |
|-----------|---------|
| 《将进酒》 | 醉态最浓，衣袍半敞，须髯微乱，举杯对月，豪迈中见悲凉 |
| 《静夜思》 | 独坐窗前，背影或侧影，孤寂收敛，月光清冷 |
| 《望庐山瀑布》 | 立于山巅，衣袂被风扬起，仰望姿态，人与自然对比 |
| 《行路难》 | 停杯投箸，眉头微蹙，愤懑不甘，非潇洒 |
| 《月下独酌》 | 花间一壶酒，与月影对饮，略带荒诞孤寂感 |

## 必须禁止的元素
- ❌ 白净无瑕的网红脸、锥子脸、大眼睛双眼皮
- ❌ 华丽发冠、金色流苏、仙侠式束发
- ❌ 发光玉佩、法器、剑、铠甲
- ❌ 蓝紫高饱和服饰、荧光色、发光粒子
- ❌ 冷峻/温柔/深情的现代男主表情
- ❌ 背景出现修仙门派、神兽、祥云特效

## AI生成Prompt

### 基础Prompt
literati romantic imagination, moderate CG quality, Chinese ancient scholarly aesthetic,
a middle-aged Chinese scholar with square face, broad forehead, thick eyebrows,
three strands of long beard, bright sharp eyes showing wild spirit,
standing tall in Tang Dynasty round-collar robe in white and ochre,
simple silk sash at waist, hair tied with scholar's cap slightly disheveled,
holding a bronze wine cup, body slightly leaning, dynamic posture,
warm ochre ink-blue pale gold palette, vast negative space, masterpiece

### 负面Prompt
[通用负向提示词] + [fantasy-ancient专属约束] +
V-shaped face, smooth baby face, delicate young male,
ornate golden crown, flowing tassels, glowing jade pendant,
magical artifacts, sword, armor, xianxia decoration,
blue-purple high saturation clothing, glowing particles,
cold stern expression, gentle tender expression,
cultivation sect background, mythical beasts, auspicious clouds effect

### 情绪变体Prompt片段
- 豪迈：looking up proudly, wine cup raised high, wild confident expression
- 醉悲：half-drunk eyes, wild laugh fading to melancholy, slightly hunched shoulders
- 沉郁：gazing into distance, lowered wine cup, deep melancholy beneath calm surface
```

---

## 示例二：李白·送别型（黄鹤楼送孟浩然之广陵，fantasy-ancient 风格）

```markdown
## 核心定位
而立之年的盛唐诗人，风流倜傥中带着离别的怅然，而非"狂放醉仙"。

## 详细特征（7维度）

| 维度 | 描述 |
|------|------|
| 年龄气质 | 约35岁，面容清朗方正，非少年亦非老迈。眉宇间有盛唐文人的自信，此刻却因离别而微蹙。蓄有修整的三缕长须，非络腮狂态 |
| 面容 | 方正脸型，眉宇微蹙，眼神悠远追随江面。嘴角似带笑意（强作洒脱），眼底藏着不舍。无醉意，无狂态，是清醒的怅惘 |
| 体态 | 立于高台，身形微侧，一手持酒杯停在胸前（未饮），另一手自然垂落或轻按栏杆。姿态舒展但不张扬，有"目送"的动态感 |
| 服饰 | 春日出游装束：浅色交领宽袍（牙白或淡青），外罩半臂或轻薄披风，无繁复纹样。腰间系深色丝绦，悬简朴锦囊或诗卷（文人标识，非法器）。衣袂被江风轻拂 |
| 发型 | 束发整齐，戴黑色幞头或儒巾，无冠饰、无流苏。发丝服帖，显庄重送别之仪，非醉后散乱 |
| 标志性动作 | 一手持酒杯停在胸前（未饮），目光远眺，身形微侧向江面 |
| 背景氛围 | 黄鹤楼头或江岸高台，烟花三月，杨花飞舞，江面波光粼粼 |

## 色彩对比逻辑
人淡而景浓：衣白/青、巾黑、须墨——人物的"淡"反衬烟花三月的"浓"，以静衬动。

## 场景互动关系

| 元素 | 处理方式 |
|------|---------|
| 孟浩然 | 已登舟远去，仅留背影或完全不出现，李白是画面唯一主体，强化"目送"的孤独 |
| 黄鹤楼 | 简笔勾勒或半隐于画面边缘，不抢主体；或仅以栏杆暗示登高 |
| 江水孤帆 | 孤帆极小，位于远景水天交界处，李白目光所向，形成画面纵深 |
| 烟花春色 | 杨花飞舞、柳色新绿、江面波光，春意越浓，离别越怅 |

## 情绪层次（按画面推进）

| 阶段 | 表情/姿态 | 关键词 |
|------|----------|--------|
| 首帧 | 举杯欲言又止，嘴角微扬（强笑） | forced smile, wine cup paused at chest, lips slightly upturned |
| 中帧 | 目光随帆移动，笑意渐收，眉头微蹙 | smile fading, eyes following distant sail, brows slightly furrowed |
| 末帧 | 帆影已渺，酒杯仍举，独对空江，怅然若失 | gazing at empty river, wine cup still raised, wistful melancholy |

## 分场景微调

| 场景/诗词 | 形象侧重 |
|-----------|---------|
| 《黄鹤楼送孟浩然之广陵》 | 深情送友，收敛狂态，清醒的怅惘，目送孤帆 |
| 《将进酒》 | 醉态最浓，衣袍半敞，须髯微乱，举杯对月，豪迈中见悲凉 |
| 《静夜思》 | 独坐窗前，背影或侧影，孤寂收敛，月光清冷 |
| 《望庐山瀑布》 | 立于山巅，衣袂被风扬起，仰望姿态，人与自然对比 |
| 《行路难》 | 停杯投箸，眉头微蹙，愤懑不甘，非潇洒 |
| 末帧 | 帆影已渺，酒杯仍举，独对空江，怅然若失 | empty river, wine cup still raised, lost in thought, deep melancholy |

## 必须禁止的元素
- ❌ 任何醉态、狂笑、仰天大笑
- ❌ 酒壶（应为酒杯，且未饮）
- ❌ 仙侠服饰、发光配饰、华丽纹样
- ❌ 锥子脸、网红五官、磨皮感
- ❌ 背景出现黄鹤楼全景喧宾夺主
- ❌ 江面出现其他船只破坏"孤帆"意境

## AI生成Prompt

### 基础Prompt
literati romantic imagination, moderate CG quality, Chinese ancient scholarly aesthetic,
a young-middle Chinese scholar about 35 with square face, slightly furrowed brows,
three strands of neat long beard, eyes gazing far into distance with hidden sorrow,
standing on high terrace in light azure Tang Dynasty cross-collar robe with thin cloak,
simple dark silk sash at waist, hair neatly tied under black futou cap,
holding a bronze wine cup paused at chest (not drinking), body slightly turned toward river,
breeze ruffling robe hem, gentle spring atmosphere, warm ochre ink-blue pale gold palette,
vast negative space, masterpiece

### 负面Prompt
[通用负向提示词] + [fantasy-ancient专属约束] +
drunk expression, wild laugh, looking up to sky, wine jug,
V-shaped face, smooth baby face, modern beauty standards,
ornate golden crown, flowing tassels, glowing jade pendant, magical artifacts,
full view of Yellow Crane Tower (must not dominate),
multiple boats on river (only ONE distant sail allowed),
xianxia decoration, glowing particles, armor

### 情绪变体Prompt片段
- 强笑：forced gentle smile, wine cup paused at chest, trying to appear cheerful
- 蹙眉：smile fading, eyes following distant sail, brows slightly furrowed
- 怅然：empty river in distance, wine cup still raised, lost in melancholy thought
```
