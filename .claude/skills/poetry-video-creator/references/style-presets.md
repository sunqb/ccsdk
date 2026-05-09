# 视觉风格预设与音色映射

## 视觉风格预设（6种）

核心策略：**降级"仙气"，升级"文气"** —— 从玄幻感转向文人画气质

| 风格ID | 名称 | 核心描述 | 色彩基调 | 角色风格 | 适用诗词 | 关键负向约束 |
|--------|------|---------|---------|---------|---------|------------|
| `ghibli-ink` | 吉卜力水墨 | 宫崎骏线条感+中国水墨淡彩，**儿童绘本般的纯真视角** | 清新翠绿+天蓝+米白 | **圆润可爱**，表情质朴天真，非网红脸 | 写景抒情（小池、春晓） | ❌ 禁止精致成人五官、华丽服饰、仙侠光效 |
| `traditional-ink` | 传统水墨 | 宋元水墨画意境，**大面积留白，计白当黑** | 水墨黑白+赭石淡彩，**禁用高饱和** | **写意简笔**，面部仅点染眉目，衣纹三两笔 | 山水田园（山居秋暝、鹿柴） | ❌ 禁止CG质感、精细五官、色彩堆砌、发光特效 |
| `watercolor` | 国风水彩 | 轻透水彩晕染，**水痕自然流动，边缘柔和** | 柔和粉彩+植物色，**低饱和高明度** | **朦胧柔美**，轮廓虚化，不强调五官细节 | 婉约词作（如梦令、声声慢） | ❌ 禁止硬边描线、浓艳色彩、清晰面部特写 |
| `gongbi` | 唐宋工笔 | 细线勾勒+层层渲染，**端庄典雅，克制精细** | 矿物色（朱砂/石青/石绿），**沉稳不跳脱** | **面部丰腴古典**（非锥子脸），衣纹流畅但不繁复 | 宫廷诗词（清平调、长恨歌） | ❌ 禁止网红锥子脸、过度装饰纹样、现代审美五官 |
| `new-chinese` | 新中式极简 | 现代几何构图+传统元素，**极简主义，90%留白** | 黑白灰+**单一点睛色**（仅一处） | **概括化剪影/符号化人物**，姿态传神即可，可无面部 | 哲理诗（登鹳雀楼、题西林壁） | ❌ 禁止任何面部细节、多色混杂、复杂背景 |
| `fantasy-ancient` | 诗意浪漫 | **文人画的浪漫想象**，适度CG质感但不失雅致 | 赭石+墨青+淡金，**降低明度，去高饱和** | **方正温润的古典面容**，服饰有层次但不堆砌纹样，气质儒雅而非仙气 | 豪放/浪漫（将进酒、望庐山瀑布） | ❌ **严禁**：仙侠网游风、网红脸、发光粒子、过度磨皮、悬浮特效、法器/神兽元素 |

## 通用负向提示词

所有风格生成时统一追加以下 negative_prompt：

```
xianxia style, fantasy cultivation, MMO game style,
internet celebrity face, V-shaped face, excessive skin smoothing,
glowing particles, magic effects, levitation effects,
overly ornate costume patterns, armor, magical artifacts,
high saturation, fluorescent colors,
dramatic rim lighting, top lighting,
modern beauty standards, big eyes with double eyelids,
cluttered background, modern objects, modern buildings, modern clothing,
text, watermark, blurry, low quality,
modern architecture, concrete, glass, steel, plastic, neon lights, 
advertisement billboard, electric pole, street lamp, air conditioner, 
car, train, bicycle, airplane, modern ship, 
smartphone, computer, watch, glasses, pen, camera, 
sofa, plastic chair, fluorescent lamp, tile floor, 
denim, nylon, synthetic fabric, high heels, sneakers, 
short hair (modern cut), dyed hair, permed hair, hair gel, 
modern makeup, false eyelashes, colored contact lens, lip gloss, manicure, 
fluorescent color, high saturation plastic texture, LED lighting, 
CG plastic texture, 3D game rendering, over-smoothing, internet celebrity filter, 
black font, sans-serif, english letters, arabic numerals, barcode, QR code, 
fast food, cola, modern packaging, disposable tableware, 
handshake, hug, modern dance, taking selfie, peace sign
```

> ⚠️ **绝对禁止**：图片中出现任何现代元素（建筑/服饰/器物/文字）

---

## 排除现代元素明细表

生成参考板和分镜图片时，以下现代元素必须排除，同时提供正向替代词。在向用户展示参考板确认时，**一并展示本表对应类别**，让用户决定哪些约束需要强化或放松。

### 一、建筑与器物

| 类别 | 禁止元素 | 正向替代 |
|------|---------|---------|
| **建筑** | 钢筋混凝土、玻璃幕墙、电线杆、路灯、空调外机、烟囱、广告牌、霓虹灯、现代桥梁、柏油马路 | 木构建筑、青砖黛瓦、茅草屋、石板路、木桥、亭台楼阁 |
| **家具** | 沙发、塑料椅、金属桌、日光灯、玻璃窗、瓷砖、马桶、现代厨具 | 案几、胡床、蒲团、青铜灯台、竹帘、纸窗、陶灶 |
| **器物** | 手机、电脑、手表、眼镜、钢笔、塑料袋、易拉罐、现代书本（胶装/白边） | 竹简、帛书、线装书、毛笔、砚台、青铜酒器、陶盏、锦囊 |
| **交通工具** | 汽车、火车、自行车、摩托车、飞机、现代轮船（蒸汽/钢铁） | 马车、牛车、小舟、竹筏、骑马、步行 |

### 二、服饰与造型

| 类别 | 禁止元素 | 正向替代 |
|------|---------|---------|
| **面料** | 牛仔、尼龙、化纤、亮片、蕾丝、西装面料、羽绒服 | 麻、葛、丝、帛、棉、皮毛 |
| **款式** | 西装、衬衫、T恤、牛仔裤、短裙、高跟鞋、运动鞋、领带、皮带（金属扣） | 深衣、襦裙、袍服、半臂、披风、布鞋、麻鞋、丝绦 |
| **发型** | 短发（现代裁剪）、染发、烫发、发胶定型、现代发夹 | 束发、簪发、冠巾、自然垂发 |
| **妆容** | 现代眉形（平眉/挑眉）、假睫毛、美瞳、唇彩、修容、美甲 | 天然肤色、黛眉、朱唇（淡）、面靥（如特定朝代） |
| **配饰** | 现代耳环、项链（非玉/非金银古法）、手表、戒指（非玉扳指）、眼镜 | 玉佩、香囊、步摇（特定场合）、纶巾、扇 |

### 三、视觉风格

| 类别 | 禁止元素 | 正向替代 |
|------|---------|---------|
| **色彩** | 荧光色、高饱和度塑料感、金属反光（非青铜/金银器）、霓虹光效 | 矿物色（朱砂、石青、石绿）、植物染、水墨黑白、赭石淡彩 |
| **光影** | 舞台追光、LED染色、闪光灯、现代摄影棚布光、轮廓光（rim light） | 自然光（日/月/烛）、柔和漫射、水墨留白、虚实相生 |
| **特效** | 粒子发光、魔法光环、悬浮特效、速度线、漫画拟声词、转场特效（闪白/叠化除外） | 水墨晕染、淡入淡出、自然烟雾、水波倒影 |
| **质感** | CG塑料感、3D游戏渲染、过度磨皮、网红滤镜（美白/瘦脸）、锐化过度 | 手绘笔触感、宣纸纹理、绢本设色、古画做旧 |

### 四、文字与符号

| 类别 | 禁止元素 | 正向替代 |
|------|---------|---------|
| **字体** | 黑体、宋体（现代印刷体）、卡通字体、英文、阿拉伯数字、标点符号（现代用法） | 篆书、隶书、行书、手写体、印章（朱砂）、无文字纯画面 |
| **标识** | 商标、Logo、二维码、条形码、现代路牌、现代旗帜 | 无标识，或以印章、题跋替代 |
| **货币** | 人民币、硬币、现代纸币 | 铜钱、银锭、布币（如剧情需要） |

### 五、行为与场景

| 类别 | 禁止元素 | 正向替代 |
|------|---------|---------|
| **动作** | 打电话、玩手机、按电梯、开车、现代礼仪（握手/拥抱/贴面）、比耶、现代舞蹈 | 作揖、跪拜、抚琴、执卷、饮酒、漫步、行礼（朝代特定） |
| **场景** | 现代城市街道、机场、火车站、医院、学校（现代建筑）、办公室、咖啡厅 | 庭院、园林、山野、江岸、酒楼、书斋、驿站、宫廷 |
| **饮食** | 快餐、可乐、现代包装食品、吸管、一次性餐具 | 酒樽、陶盏、竹箸、食盒、荷叶包、现场烹制 |

### 六、按朝代细化的补充约束

| 朝代 | 额外禁止 | 特殊注意 |
|------|---------|---------|
| **先秦** | 纸张（用竹简/帛书）、椅子（席地而坐）、马镫 | 服饰简朴，无复杂纹样 |
| **汉唐** | 桌椅组合（席地/榻）、茶叶冲泡法（唐代煎茶）、旗袍 | 胡服元素（唐代特定），开放大气 |
| **宋元** | 太师椅（宋代才出现）、眼镜、烟草 | 文人气质，极简美学 |
| **明清** | 西装影响、眼镜普及（明代后期才传入）、钟表 | 服饰繁复但非戏服化 |

## 各风格 style_prefix 模板

| 风格ID | style_prefix |
|--------|-------------|
| `ghibli-ink` | anime style, Studio Ghibli inspired, Chinese ink-wash aesthetic, soft warm lighting, innocent childlike perspective, rounded cute characters, pastel colors, masterpiece, best quality |
| `traditional-ink` | traditional Chinese ink-wash painting, minimalist brushwork, Song Dynasty aesthetic, monochrome with light color wash, vast negative space, essence over detail, masterpiece |
| `watercolor` | soft watercolor illustration, pastel color blending, Chinese aesthetic, dreamy atmosphere, delicate soft edges, water flow marks, low saturation high lightness, masterpiece |
| `gongbi` | fine detailed Chinese gongbi painting, mineral pigments, precise restrained brushwork, Tang Dynasty court style, dignified classical beauty, masterpiece |
| `new-chinese` | modern minimalist Chinese style, geometric composition, monochrome with single accent color, 90% negative space, symbolic silhouette, masterpiece |
| `fantasy-ancient` | literati romantic imagination, moderate CG quality, Chinese ancient scholarly aesthetic, warm ochre ink-blue pale gold palette, refined classical face, elegant restraint NOT fantasy, masterpiece |

## 旁白音色推荐映射

> ⚠️ 所有音色已通过 MiniMax TTS API 实际调用验证，均可正常使用。

### 首选推荐（按诗词类型匹配）

| 音色ID | 别名 | 声线特征 | 风格适配 | 诗词类型适配 | 推荐语速 | 推荐场景 |
|--------|------|---------|---------|------------|---------|---------|
| `Chinese_radio_host_male_vv1` | 电台主持 | 低沉沉稳，浑厚磁性，沉浸式 | traditional-ink, new-chinese | 山水田园、哲理诗、怀古诗 | 3-4字/秒 | **古诗词旁白首选**，沉稳叙事感，适合意境深远的经典诗词 |
| `Chinese_radient_storyteller_vv1` | 说书爷爷 | 沙哑鼻音，引人入胜，极强表现力 | traditional-ink, gongbi | 叙事诗、长诗、乐府 | 3-4字/秒 | 适合有故事性的长篇诗词（如琵琶行、长恨歌），说书人代入感 |
| `Chinese (Mandarin)_Reliable_Executive` | 沉稳高管 | 低沉厚实，磁性，从容不迫 | fantasy-ancient, new-chinese | 豪放词、边塞诗 | 3-5字/秒 | 豪迈壮阔类（将进酒、满江红），声线有力量感和权威感 |
| `hunyin_6` | 舒朗男声 | 清亮干脆，意气风发 | fantasy-ancient, ghibli-ink | 少年意气、送别诗、行旅诗 | 4-5字/秒 | 适合少年侠客/热血青年角色（如少年行、送别诗中的行旅者） |
| `Chinese (Mandarin)_Male_Announcer` | 播报男声 | 清澈干净，自然流畅，邻家大哥哥 | watercolor, ghibli-ink | 写景抒情、思乡诗 | 4-5字/秒 | 亲切自然，适合温情叙事（静夜思、春晓），不过于庄重 |
| `Chinese (Mandarin)_Gentle_Senior` | 温柔学姐 | 温婉柔和，娓娓道来，富有感染力 | watercolor, gongbi | 婉约词、闺怨诗 | 3-4字/秒 | 温柔知性，适合婉约细腻的词作（声声慢、如梦令） |
| `Chinese (Mandarin)_Sweet_Lady` | 甜美女声 | 甜美细腻，舒缓自然，邻家亲切 | ghibli-ink, watercolor | 儿童诗词、田园小诗 | 3-5字/秒 | 儿童友好，适合小学诗词启蒙（小池、咏鹅） |
| `Chinese (Mandarin)_Cute_Spirit` | 憨憨萌兽 | 软萌稚嫩，轻快活泼 | ghibli-ink | 幼儿古诗启蒙 | 3字/秒 | 学前/低年级专用，萌系配音（春晓、咏鹅） |

### 备选音色（旧版，仍可用）

| 音色ID | 声线特征 | 适用场景 |
|--------|---------|---------|
| `Chinese (Mandarin)_Warm_Bestie` | 温暖亲切女声 | 通用替代，无明确性格偏向 |
| `Chinese (Mandarin)_Female_Young` | 年轻清亮女声 | 青少年向，轻快诗词 |
| `Chinese (Mandarin)_Female_Mature` | 成熟知性女声 | 传统水墨/工笔向 |
| `male-qn-jingying` | 精英男声 | 新中式极简向 |
| `male-qn-qingse` | 青涩男声 | 吉卜力水墨向 |
| `preschool_female` | 学前女声 | 幼儿启蒙 |
| `preschool_male` | 学前男声 | 幼儿启蒙 |

### 音色选择决策树

```
古诗词旁白音色选择：
├─ 旁白风格是课标模板？
│  ├─ 通用型 / 冷暖对比型 → 电台主持 (Chinese_radio_host_male_vv1)
│  ├─ 知人论世型 / 一字立骨型 / 假如改写型 / 文化密码型 → 沉稳高管 (Chinese (Mandarin)_Reliable_Executive)
│  ├─ 侦探解谜型 / 因果追问型 → 播报男声 (Chinese (Mandarin)_Male_Announcer)
│  ├─ 画面追踪型 / 以画解诗型 → 温柔学姐 (Chinese (Mandarin)_Gentle_Senior)
│  ├─ 声韵品味型 / 古今对话型 / 诗人朋友圈型 → 甜美女声 (Chinese (Mandarin)_Sweet_Lady)
│  └─ 知人论世型（沉郁） → 舒朗男声 (hunyin_6)
├─ 旁白风格是年龄风格？
│  ├─ recitation（纯诵读）→ 电台主持 (Chinese_radio_host_male_vv1)
│  ├─ story（故事化）→ 说书爷爷 (Chinese_radient_storyteller_vv1)
│  ├─ child（儿童）→ 甜美女声 (Chinese (Mandarin)_Sweet_Lady)
│  ├─ preschool（学前）→ 憨憨萌兽 (Chinese (Mandarin)_Cute_Spirit)
│  └─ 其他讲解型 → 看诗词气质
│     ├─ 豪放壮阔 → 沉稳高管 (Chinese (Mandarin)_Reliable_Executive)
│     ├─ 少年意气 → 舒朗男声 (hunyin_6)
│     ├─ 婉约细腻 → 温柔学姐 (Chinese (Mandarin)_Gentle_Senior)
│     ├─ 温情叙事 → 播报男声 (Chinese (Mandarin)_Male_Announcer)
│     └─ 意境深远 → 电台主持 (Chinese_radio_host_male_vv1) ← 默认首选
```

### 旁白风格×音色推荐矩阵

**课标模板音色**：

| 旁白风格 | 首选音色 | 备选音色 | 推荐语速 |
|---------|---------|---------|---------|
| 通用型 | 电台主持 | 沉稳高管 | 3.3-3.7字/秒 |
| 一字立骨型 | 沉稳高管 | 电台主持 | 3.3-3.7字/秒 |
| 声韵品味型 | 甜美女声 | 温柔学姐 | 2.7-3.0字/秒 |
| 侦探解谜型 | 播报男声 | 电台主持 | 3.3-3.7字/秒 |
| 因果追问型 | 播报男声 | 电台主持 | 3.3-3.7字/秒 |
| 假如改写型 | 沉稳高管 | 播报男声 | 3.3-3.7字/秒 |
| 画面追踪型 | 温柔学姐 | 甜美女声 | 3.3-3.7字/秒 |
| 冷暖对比型 | 电台主持 | 沉稳高管 | 3.3-3.7字/秒 |
| 以画解诗型 | 温柔学姐 | 甜美女声 | 3.3-3.7字/秒 |
| 古今对话型 | 甜美女声 | 温柔学姐 | 3.3-3.7字/秒 |
| 诗人朋友圈型 | 甜美女声 | 温柔学姐 | 3.3-3.7字/秒 |
| 文化密码型 | 沉稳高管 | 电台主持 | 3.3-3.7字/秒 |
| 知人论世型 | 沉稳高管 | 电台主持 | 3.3-3.7字/秒 |

**年龄风格音色**（备选）：

| 旁白风格 | 首选音色 | 备选音色 | 推荐语速 |
|---------|---------|---------|---------|
| child | 甜美女声 | 播报男声 | 3.3-3.7字/秒（200-220字/分钟） |
| teen | 电台主持 | 温柔学姐 | 3.3-3.7字/秒（200-220字/分钟） |
| adult | 沉稳高管 | 电台主持 | 3.3-3.7字/秒（200-220字/分钟） |
| preschool | 憨憨萌兽 | 甜美女声 | 2.5-3字/秒（150-180字/分钟，略慢） |
| story | 说书爷爷 | 舒朗男声 | 3.3-3.7字/秒（200-220字/分钟） |
| recitation | 电台主持 | 沉稳高管 | 豪放3.3（200），婉约2.7（160），禅意2.2（130） |

## 时长控制

语速统一标准：200-220字/分钟（preschool略慢150-180字/分钟，recitation按诗词类型调整）

| 时长 | 字数 | 用途 |
|------|------|------|
| 3-5秒 | 10-15字 | 诗眼句、过渡词 |
| 8-10秒 | 25-35字 | 单句解析、情绪转折 |
| 15-20秒 | 50-70字 | 一联赏析、场景铺陈 |
| 25-30秒 | 80-110字 | 作者背景、总结升华 |

各分镜模板时长上限详见 [storyboard-templates.md](storyboard-templates.md)

## 色彩情绪映射

| 情绪 | 色调 |
|------|------|
| 平静 | 浅翠+浅蓝 |
| 欢快 | 暖金+嫩绿 |
| 感伤 | 灰蓝+淡紫 |
| 惊喜 | 明黄+翠绿 |
| 温暖 | 橙金+米白 |
| 庄重 | 深褐+暗金 |
| 豪迈 | 浓墨+赤金 |
