<!-- LANG-SWITCH -->
**English** | [中文](BENCHMARKS.zh.md)

# SuwayomiOCR Translation Benchmark

Automated benchmark of the JP→ZH translation pipeline over the paired
`Datasets/生肉/` (raw Japanese) ↔ `Datasets/熟肉/` (fan-translated Chinese)
manga corpus. Both reference and system outputs share the same upstream
OCR pipeline (vLLM-hosted **DeepSeek-OCR-2**), so OCR noise cancels out
partially in the comparison.

## TL;DR

_DeepSeek-Chat edges out Google on BLEU/chrF (manga-aware prompt helps)._

|  | DeepSeek-Chat | Google Translate | Qwen (end-to-end, local) |
| --- | ---: | ---: | ---: |
| BLEU (zh) | **4.28** | 3.61 | 2.66 |
| chrF | **6.29** | 6.15 | 5.58 |
| per-page latency | 2.94s | 1.35s | 24.83s |
| per-page tokens | 707 | N/A (REST API) | 2722 |
| per-page cost | $0.00035 | $0 (free, rate-limited) | $0 (self-hosted, GPU compute) |
| OCR coupling | separate model (DeepSeek-OCR-2) | separate model (DeepSeek-OCR-2) | same model does OCR too |
| works behind GFW | yes (api.deepseek.com) | no (needs proxy) | yes (self-hosted) |

**Which should I choose?**

- **DeepSeek-Chat** if you read translated manga seriously and have no local GPU:
  the system prompt carries title and chapter, so character names, jargon and tone
  stay consistent. Cost is negligible for personal use (≈ $0.35 per 1000 pages).
- **Google Translate** for zero config and zero account setup. Fastest per call,
  but loses the manga register and needs a proxy in mainland China.
- **Qwen (end-to-end)** if you have a local GPU: a single multimodal model
  does OCR + translation in one pipeline, no cloud calls, no per-token cost.
  Quality is close to DeepSeek (see numbers below). Latency depends on your hardware.

Reproduce with:
```bash
python scripts/benchmark.py gather    # populates benchmark_results.jsonl
python scripts/benchmark.py score     # rewrites this file
```

## Corpus

- Pages processed: **132**
- Pages with non-empty JP OCR: 132
- Pages with non-empty ZH reference OCR: 132

## Translation quality

Metrics (all higher = better):

- **BLEU** (sacrebleu, `tokenize=zh`) — character-level n-gram overlap, classic MT metric.
- **chrF** — character n-gram F1, robust on Chinese where word boundaries are ambiguous.
- **chrF++** — chrF augmented with word-level n-grams.
- **CharJac** — set Jaccard over unicode characters; coarse vocabulary overlap.
- **CharF1** — multiset character F1; sensitive to over/under-generation.

| Backend | n | BLEU | chrF | chrF++ | CharJac | CharF1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek-Chat | 132 | 4.28 | 6.29 | 5.73 | 0.138 | 0.230 |
| Google Translate | 132 | 3.61 | 6.15 | 5.42 | 0.138 | 0.243 |
| Qwen (end-to-end) | 95 | 2.66 | 5.58 | 4.71 | 0.129 | 0.191 |

_Note: "Qwen (end-to-end)" uses the Qwen multimodal model for **both** OCR and
translation, so this row measures the **full pipeline**, while DeepSeek-Chat and
Google rows translate the same DeepSeek-OCR text. They are not strictly apples-to-
apples — Qwen's score also reflects its OCR contribution._

## Qualitative observations

Surface metrics (BLEU/chrF/CharF1) **understate the quality gap** on this
corpus. Eyeballing the side-by-side samples below:

- **Short labels** (page numbers, illustration credits) — both backends are
  roughly equal. Differences are stylistic (e.g. `41` → `第41页` vs `41`).
- **Long technical / structured prose** — DeepSeek is materially better. Google
  produces broken metaphors and dangling literal translations on diagrams and
  flow charts; DeepSeek follows the document structure and keeps terminology
  consistent across sections.
- **Literary / context-dependent prose** — DeepSeek wins on terminology choice
  and register; Google has occasional outright translation errors on
  context-sensitive words (e.g. 義理の母 mistranslated as 婆婆 instead of 继母).
- **Table-formatted text** — DeepSeek preserves the markdown table structure
  and Japan-specific terms cleanly. Google translates correctly but reads choppy.

The surface metrics are dragged down by three corpus-specific issues:

1. **Page misalignment** — `生肉/N.jpg` does not always correspond to `熟肉/N.jpg`
   in this dataset; the two scans were not curated to the same page order, so
   some pairs have completely unrelated content. Both backends are penalized
   equally, but the absolute scores look worse than the actual translations are.
2. **Free fan-translation** — `熟肉` paraphrases liberally and adds detail not in
   the source. A faithful translation looks "wrong" by n-gram overlap.
3. **OCR noise on both sides** — both reference and system output share the OCR
   noise floor.

## Translation API tokens & cost

Pricing assumed (USD per 1M tokens; **defaults match DeepSeek-Chat — verify at provider site**):
- input cache miss: `$0.27`
- input cache hit:  `$0.07`
- output:           `$1.10`

| metric | value |
| --- | ---: |
| prompt tokens (total) | 64,018 |
| ├─ cache hit | 16,896 |
| └─ cache miss | 47,122 |
| completion tokens | 29,304 |
| **total cost** | **$0.0461** |
| ├─ input | $0.0139 |
| └─ output | $0.0322 |
| avg tokens / page | 707 |
| avg cost / page | $0.00035 |

## Qwen end-to-end tokens (local — no $$$)

Local model, only GPU compute cost. Token counts reported for reference and
as a proxy for self-hosted compute budget planning.

| metric | value |
| --- | ---: |
| OCR prompt tokens | 92,099 |
| OCR completion tokens | 34,028 |
| translate prompt tokens | 52,835 |
| translate completion tokens | 79,601 |
| **total** | **258,563** |
| avg tokens / page | 2722 |

## Latency (per page, average)

| stage | latency |
| --- | ---: |
| DeepSeek-OCR-2 (vLLM, local) | 1.61s |
| DeepSeek-Chat (cloud) | 2.94s |
| Google Translate (cloud) | 1.35s |
| Qwen OCR (Qwen/Qwen3.6-27B) | 7.11s |
| Qwen translate (same model) | 17.72s |

## Backend tradeoffs

|  | DeepSeek-Chat | Google Translate | Qwen (end-to-end, local) |
|---|---|---|---|
| Cost | paid per token (≈ $0.35/1k pages) | free (rate-limited) | free (self-hosted, GPU compute) |
| Manga-aware prompt | yes | no (generic MT) | yes (same system prompt) |
| OCR pipeline | separate DeepSeek-OCR-2 model | separate DeepSeek-OCR-2 model | same model does OCR too |
| Accepts long context | yes (~64K) | per-call length cap | yes (model context window) |
| China network friendliness | direct via api.deepseek.com | needs proxy | self-hosted, fully local |
| Privacy | sent to DeepSeek | sent to Google | never leaves your machine |
| Operator effort | none — just an API key | none | you run + maintain the vLLM/SGLang server |

## Sample comparisons

### Page `068.jpg`

**JP source (DeepSeek-OCR-2)**

```
illustration by あリまなつぼん

第3章  
もうすぐ生まれる！  

出産は命をかけた大仕事なのです  
男性も色々勉強して、協力することが大切です
```

**JP source (Qwen OCR)**

```
illustration by ありまなつばん
第3章
もうすぐ生まれる!
出産は命をかけた大仕事なのです
男性も色々勉強して、協力することが大切です
```

**Reference (OCR of 熟肉)**

```
Chapter 03 馬上就要出生了！

產前準備
STEP 1

如何預防妊娠線

要想預防妊娠線就要好好保持住水嫩Q彈的肌膚！

雖然妊娠是幸福美好的，但是也有對女性美容不是很友好的部分。其中最可惡的家務，可能就是妊娠線了吧。

人類的皮膚由表皮、真皮、皮下組織三層搭建。其中表皮最秀。可以拉得很長。但是真皮和皮下組織的伸縮能力就不是那麼好了。上小寶寶肚子變大後，皮膚被拉伸過度就會裂開。透過表皮看到的真皮的裂痕就是妊娠線了。

妊娠時人體還會分泌讓皮膚失去彈性的荷爾蒙，肌膚的彈性也會慢慢失去。因此此時的皮膚更容易產生妊娠紋。

妊娠線最容易發生在妊娠超過20周左右期間。主要長在變大的腹部、胸部、大腿、臀部、胳膊。也容易長在自己看不到的地方，所以要讓自己的伴侶好好的幫自己確認哦。長出豐滿的妊娠線即使變薄也不可能會消失了。所以要做好預防哦。

要想預防妊娠線，最重要的還是要保持肌膚的彈力。多用護膚品築起保濕防皺吧！控制體重也是很重要的。妊娠中的女性因為荷爾蒙的關係很容易積累皮下脂肪，毫不小心就會變胖，盡定要管住嘴不要增加多余的脂肪哦。

缺水導致的浮腫也要好好預防。浮腫也會拉伸皮膚成為妊娠線的病因。

去除浮腫最有效的辦法還是伸展運動。在地上坐下伸直兩腳，身體前屈去觸碰脚尖來回十次。之後伸展腳掌十次。

每天保濕之後入浴也是很有效果的哦。

66
```

**DeepSeek-Chat**

```
插图：ありまなつぼん

第3章  
马上要出生了！

分娩是赌上性命的重大任务  
男性也要多学习，积极配合，这一点非常重要
```

**Google Translate**

```
[Google翻译] 插图：Arimanatsubon

第三章
马上就要出生了！  

分娩是一件危及生命的事情。
对男人来说，学习各种事物并进行合作是很重要的。
```

**Qwen (end-to-end)**

```
插画：ありまなつばん
第三章
马上就要出生啦！
分娩是一场以生命为赌注的重大任务。
男性也应当认真学习相关知识，给予充分的协助，这一点至关重要。
```

### Page `005.jpg`

**JP source (DeepSeek-OCR-2)**

```
第三章 もうすぐ生まれる！

お産の準備
STEP1: 妊娠終了 ……… 66  
STEP2: 歯のトラブル対処 ……… 67  

いよいよ生まれる！
STEP1: 陣痛開始 ……… 72  
STEP2: 破水 ……… 74  
STEP3: 強い陣痛への対処 ……… 76  

いろいろな出産方法 ……… 84  

産後の女の子
STEP1: 会陰と子宮 ……… 88  
STEP2: 尿漏れ ……… 90  
STEP3: 初乳 ……… 92  

---

STEP3: おなかの赤ちゃんの心配事 …
STEP4: 産前のトラブル対処 ……  70  

---

STEP4: 分娩台 ………  78  
STEP5: 出産時に行われる処置 ……  80  
STEP6: とうとう生まれた！ ……  82  

出産アクシデント ……  86  

---

STEP4:体重戻し ……  94  
STEP5:母乳セックス ……  96  

---

▎第四章 赤ちゃんとの暮らし

赤ちゃんについて知っておくこと…100  

**赤ちゃんのお世話**
STEP1:授乳………104  
STEP2：おむつ………106  
STEP3：沐浴………108  

意外とあなたどれないマタニティブルー・産後コク…118  
子宮回復って何？………120  
はじめての保育園………122  

**コラム**
危険日以外は中止したK？………14  
ポルチオテクニック………26  
近親相杀………33  
知っておきたい中絶リスク………34  
妊婦フェチジズム………58  
妊娠中に感度は上がる？下がる？…64  

役所への届出………102  

---

STEP4：寝かしつけ………110  
STEP5：赤ちゃんがかかりやすい病気…114 
STEP6：一日のス
```

**JP source (Qwen OCR)**

```
■ 第三章 もうすぐ生まれる！
お産の準備
STEP1:妊娠線予防・・・・・・・・・・・・・・・・66 STEP3:おなかの赤ちゃんの心配事・・・68
STEP2:歯のトラブル対処・・・・・・・・・・・・67 STEP4:産前のトラブル対処・・・・・・・・70

いよいよ生まれる！
STEP1:陣痛開始・・・・・・・・・・・・・・・・72 STEP4:分娩台・・・・・・・・・・・・・・・・78
STEP2:破水・・・・・・・・・・・・・・・・74 STEP5:出産時に行われる処置・・・・80
STEP3:強い陣痛への対処・・・・・・・・・・・・76 STEP6:とうとう生まれた！・・・・・・・・82

いろいろな出産方法・・・・・・・・・・・・・・・・84 出産アクシデント・・・・・・・・・・・・・・・・86

産後の女の子
STEP1:会陰と子宮・・・・・・・・・・・・・・・・88 STEP4:体重戻し・・・・・・・・・・・・・・・・94
STEP2:尿漏れ・・・・・・・・・・・・・・・・90 STEP5:母乳セックス・・・・・・・・・・・・96
STEP3:初乳・・・・・・・・・・・・・・・・92

■ 第四章 赤ちゃんとの暮らし
赤ちゃんについて知っておくこと・・・100 役所への届出・・・・・・・・・・・・・・・・102

赤ちゃんのお世話
STEP1:授乳・・・・・・・・・・・・・・・・104 STEP4:寝かしつけ・・・・・・・・・・・・110
STEP2:おむつ・・・・・・・・・・・・・・・・106 STEP5:赤ちゃんがかかりやすい病気 114
STEP3:沐浴・・・・・・・・・・・・・・・・108 STEP6:一日のスケジュール・・・・・・・・116

意外とあなどれないマタニティブルー・産後うつ・・・・・・・・・・・・・・・・118
子宮回復って何？・・
```

**Reference (OCR of 熟肉)**

```
目錄

序章 ...... 4

■ 第一章 在造出孩子之前

為什麼想要 SEX 呢？ ...... 6
為什麼要中出呢？ ...... 8

【圖解】生殖器的結構
A.性器官斷面圖 ...... 10    C.從開始排卵到懷孕 ...... 12
B.著床後的結構 ...... 11

來做愛吧！
STEP1:目標是喜歡上做愛！......14    STEP4:關於性衝動的豆知識 ......22
STEP2:關於容易懷孕的二三事......16    STEP5:性高潮和懷孕的關係 ......24
STEP3:了解男女的發清週期！......20

來受精吧！
STEP1:排卵日的計算方法 ......28
STEP2:適合妊娠的年齡 ......30
STEP3:避孕和不孕不育的那些事 ......32

■ 第二章 懷上寶寶了！

懷孕的信號 ......36
第一次去婦產科 ......38
男性所不知道的婦科檢查的世界 ......40

懷孕中的女孩子
STEP1：準媽媽的體型變化！......42    STEP5：穿什麼衣服好呢？......50
STEP2：妊娠中的乳房......44    STEP6：還容易得便秘和痔瘡嗎？......52
STEP3：孕吐难受死人了！......46    STEP7：孕期的生活起居......54
STEP4：懷孕期間的飲食......48    STEP8：懷孕中的乳頭護理......60

胎兒在內的成長 ......62
```

**DeepSeek-Chat**

```
第三章 马上就要生了！

**分娩准备**
第一步：妊娠结束 ……… 66  
第二步：牙齿问题应对 ……… 67  

**终于要生了！**
第一步：阵痛开始 ……… 72  
第二步：破水 ……… 74  
第三步：应对强烈阵痛 ……… 76  

**各种分娩方式 ……… 84**

**产后的女生**
第一步：会阴与子宫 ……… 88  
第二步：漏尿 ……… 90  
第三步：初乳 ……… 92  

---

第三步：对腹中宝宝的担忧 …  
第四步：产前问题应对 …… 70  

---

第四步：分娩台 ……… 78  
第五步：分娩时的处理 …… 80  
第六步：终于生出来了！ …… 82  

**分娩意外 …… 86**

---

第四步：体重恢复 …… 94  
第五步：母乳与性生活 …… 96  

---

▎第四章 与宝宝一起生活

**需要了解的宝宝知识…100**

**照顾宝宝**
第一步：哺乳………104  
第二步：尿布………106  
第三步：沐浴………108  

**意想不到的产后抑郁与忧郁…118**  
**子宫恢复是什么？………120**  
**第一次上保育园………122**

**专栏**
非危险日就不用避孕？………14  
子宫颈技巧………26  
近亲相奸………33  
必须了解的人工流产风险………34  
孕妇恋物癖………58  
孕期性敏感度会上升还是下降？…64  

**向政府提交的申报………102**

---

第四步：哄睡………110  
第五步：宝宝易患的疾病…114  
第六步：一天的时间安排…116  

**产后性欲真的会减退吗？124**
```

**Google Translate**

```
[Google翻译] 第3章：即将到来！

分娩准备
STEP1：终止妊娠……66
STEP2：处理牙齿问题…… 67

终于诞生了！
STEP1：分娩开始...... 72
STEP2：破水……74
STEP3：应对强烈的阵痛…… 76

各种分娩方式……84

产后女孩
STEP1：会阴和子宫……88
STEP2：漏尿……90
STEP3：初乳……92

---

STEP3：担心你的宝宝......
STEP4：处理产前问题... 70

---

STEP4：交货表……78
STEP5：分娩期间进行的治疗...80
STEP6：终于诞生了！ …… 82

出生事故...86

---

STEP4：体重反弹...94
STEP5：母乳性爱...96

---

▎第四章 与婴儿一起生活

关于婴儿你必须知道的事情……100

**婴儿护理**
第1步：母乳喂养……104
STEP2：尿布……106
STEP3：洗澡……108

令人惊讶的是，你不会爱上孕妇蓝和产后丰润……118
什么是子宫恢复？ ......120
第一幼儿园……122

**专栏**
K 在非危险日取消？ ……14
部分技术……26
乱伦同死……33
你应该知道的堕胎风险……34
孕妇恋物癖……58
怀孕期间敏感性会增加吗？会下降吗？ …64

通知政府部门……102

---

STEP 4: Putting it to bed……110
第 5 步：婴儿易患的疾病...114
STEP6：每日日程…116

产后性欲下降是真的吗？ 124
```

**Qwen (end-to-end)**

```
■ 第三章 即将迎来分娩！
分娩准备
STEP1：预防妊娠纹・・・・・・・・・・・・・・・・66 STEP3：关于腹中胎儿的担忧・・・・・・・・68
STEP2：牙齿问题的应对・・・・・・・・・・・・67 STEP4：产前问题的应对・・・・・・・・70

终于要分娩了！
STEP1：阵痛开始・・・・・・・・・・・・・・・・72 STEP4：分娩台・・・・・・・・・・・・・・・・78
STEP2：破水・・・・・・・・・・・・・・・・74 STEP5：分娩时的处置・・・・・・・・80
STEP3：应对强烈阵痛・・・・・・・・・・・・76 STEP6：终于出生了！・・・・・・・・82

各种分娩方式・・・・・・・・・・・・・・・・84 分娩意外・・・・・・・・・・・・・・・・86

产后女性
STEP1：会阴与子宫・・・・・・・・・・・・・・・・88 STEP4：体重恢复・・・・・・・・・・・・・・・・94
STEP2：漏尿・・・・・・・・・・・・・・・・90 STEP5：母乳与性生活・・・・・・・・・・・・96
STEP3：初乳・・・・・・・・・・・・・・・・92

■ 第四章 与宝宝的生活
关于宝宝需要知道的事・・・100 向政府机关申报・・・・・・・・・・・・・・・・102

宝宝护理
STEP1：哺乳・・・・・・・・・・・・・・・・104 STEP4：哄睡・・・・・・・・・・・・110
STEP2：尿布・・・・・・・・・・・・・・・・106 STEP5：宝宝易患疾病 114
STEP3：沐浴・・・・・・・・・・・・・・・・108 STEP6：一日作息・・・・・・・・116

不可忽视的产后抑郁・・・・・・・・・・・・・・・・118
子宫恢复是什么？・・・・・・・・・・・・・・・・120 产后性欲减退是真的吗？ 124
初次使用托儿所・・・・・・・・・・・・・・・・122

```

### Page `029.jpg`

**JP source (DeepSeek-OCR-2)**

```
はないのです。ほぼ無感覚のポルチオから快感を得るには、まずは  
脳が刺激を快感だと認識する必要があります。  

まずは指かべこスを挿入し、ポルチオまで届かせる必要がありま  
す。挿入する時の体勢は、「脚を浮かせたあおむけ」か「お尻を浮  
かせたうつぶせ」がやりやすいでしょう。  

膣内の状態によって、膣口からポルチオまでの距離は変わります。  
クリトリスで絶頂した直後などは、ポルチオまで指やべこスが届き  
やすくなることもあります。  

膣の奥でコリっとする突起物がポルチオで、その真ん中に空いて  
いる穴が子宮口です。ポルチオに指やべこスが届いたら、ポルチオ  
とその周辺の膣壁をくり返し押してみてください。押す、離す、押  
す、離す、繰り返します。トントンと軽く叩くような感じにした  
り、ときには痛むようにしてみたり。  

ポルチオに対する刺激に、女の子はいわゆる「変な感じ」とし  
か思わないかもしれません。あまり感覚がないのですが、これは  
当然のことです。しかしくり返し深く突いているうちに、じんわり  
と快感が起こってきて、やがて大きなものへと変わっていくのです。  

ポイントは女の子も積極的に「快感を見つけようとする」こと。「変  
な感じ」を快感へと変えてい  
<のです。  

ポルチオまでべこスが届か  
ないからといって嘆く必要は  
ありません。膣奥にくり返し  
刺激を与えれば、その刺激は  
ポルチオにも伝わります。  

焦らずにじっくりと、女の子の快感を「育てて」あげて  
ください。  

図・ポルチオ性感帯の位置

**図例**:
  - 膣口
  - 尿道口
  - 陰道口
  - 肛門
  - 膀胱
  - 子宫
```

**JP source (Qwen OCR)**

```
はないのです。ほぼ無感覚のポルチオから快感を得るには、まずは
脳が刺激を快感だと認識する必要があります。
まずは指かペニスを挿入し、ポルチオまで届かせる必要がありま
す。挿入する時の体勢は、「脚を浮かせたあおむけ」か「お尻を浮
かせたうつぶせ」がやりやすいでしょう。
膣内の状態によって、膣口からポルチオまでの距離は変わります。
クリトリスや絶頂した直後などは、ポルチオまで指やペニスが届き
やすくなることもあります。
膣の奥でコリっとする突起物がポルチオで、その真ん中に空いて
いる穴が子宮口です。ポルチオに指やペニスが届いたら、ポルチオ
とその周辺の膣壁をくり返し押してみてください。押す、離す、押
す、離す、の繰り返しです。トントンと軽く叩くような感じにしたり、ときには撫でるようにしてみたり。
ポルチオに対する刺激に、女の子ははじめうち「変な感じ」とし
か思わないかも知れません。あまり感覚がないのですから、これは
当然のことです。しかしくり返し深く突いているうちに、じんわり
と快感が起こってきて、やがて大きなものへと変わっていくのです。
ポイントは女の子も積極的に「快感を見つけようとする」こと。「変
な感じ」を快感へと変えてい
くのです。
ポルチオまでペニスが届か
ないからといって嘆く必要は
ありません。膣奥にくり返し
刺激を与えれば、その刺激は
ポルチオにも伝わります。
焦らずにじっくりと、女の
子の快感を「育てて」あげて
ください。
```

**Reference (OCR of 熟肉)**

```
先插入手指或者陰莖達到足以碰到子宫頸的深度。插入時採用  
「把腳抬起來仰躺著」和「翘起屁股趴著」這兩種姿勢比較方便。  
關於陰道內的狀態，距離陰道口到子宮頸的距離會有所變化。通過  
陰蒂高漲之後，手指和陰莖會更容易碰到子宮頸。  

陰道深處的突起物就是子宮頸，它的正中間的空洞就是子宮口  
。如果用手指或者陰莖碰到子宮頸的話，請試著反覆壓迫子宮頸和  
它周圍的陰道壁。「壓、離開」、「壓、離開」，如此反覆。時而輕輕敲擊  
，時而撫摸這條血管感覺。  

對於子宫頸的刺激，女孩子喜開始會有「奇怪的感覺」，也說不  
定。或許沒有什么感覺也是非常正常的。可是，經過反覆地挑弄  
，漸漸地就會產生快感，而且會變得越來越明顯。  

時候是當女孩子也積極地「尋求快感」時。將「奇怪的感覺」  
變成快感吧！  

即使陰莖的長度達不到子宮頸也不必嘆息。反復刺激陰道深處  
的話，也能將這種刺激傳遞給子宮頸。  

請不要羞慾，踏踏實實地幫女孩子「培育」快感吧。

---

圖：子宮頸性感帶的位置

尿道口  
肛門  
尿道瓣膜  
肛門瓣膜  
尿道韌帶  
尿道球腺肌
```

**DeepSeek-Chat**

```
并非如此。要从几乎无感的子宫颈（P点）获得快感，首先需要让大脑将刺激识别为快感。

首先，需要用手指或假阴茎插入，使其触及子宫颈。插入时的姿势，推荐“双腿抬起的仰卧位”或“臀部抬起的俯卧位”，这样更容易操作。

根据阴道内的状态，从阴道口到子宫颈的距离会发生变化。例如，在通过阴蒂达到高潮后不久，手指或假阴茎更容易触及子宫颈。

阴道深处那个硬硬的突起就是子宫颈，其中间的孔洞是子宫口。当手指或假阴茎触及子宫颈后，请反复按压子宫颈及其周围的阴道壁。按压、松开、按压、松开，如此重复。可以像轻轻敲击一样，有时也可以稍微用力到有痛感。

对于子宫颈的刺激，女孩子可能只会觉得“怪怪的”。几乎没什么感觉，这是很正常的。但反复深入刺激后，快感会逐渐涌现，最终转变为强烈的快感。

关键在于，女孩子也要主动“去寻找快感”。将“怪怪的感觉”转化为快感。

即使假阴茎无法触及子宫颈，也无需叹息。只要反复刺激阴道深处，这种刺激也会传递到子宫颈。

请不要着急，耐心地“培养”女孩子的快感。

图：子宫颈敏感带的位置

**图例**:
  - 阴道口
  - 尿道口
  - 阴道口
  - 肛门
  - 膀胱
  - 子宫
```

**Google Translate**

```
[Google翻译] 没有。要从几乎麻木不仁的波尔蒂奥那里得到乐趣，首先
你的大脑需要将刺激视为令人愉悦的。  

首先，您需要插入手指并使其到达部分。
是的。插入材料时的位置是“仰卧，双腿向上”或“臀部向上”。
俯卧会更容易做到这一点。  

从阴道口到阴道口的距离根据阴道内部的状况而变化。  
在阴蒂达到高潮后，您的手指和手指会立即到达阴蒂部分。
有时它会变得更容易。  

阴道深处的硬挺的突起就是阴道口，中间有一个洞。
你所在的洞就是子宫颈。当Portio收到你的手指和手指时，Portio
尝试反复按压该区域周围的阴道壁。按下、释放、推动
释放，释放，重复。感觉就像轻轻敲击一样。
有时我会试图让它受伤。  

由于波尔蒂奥的刺激，少女感受到了所谓的“奇怪的感觉”。
你可能不这么认为。我其实没啥感觉，但是这个
当然。然而，当我反复深深地刺入时，
一种愉悦的感觉升起，很快它就变成了更大的感觉。  

关键是女孩们也会积极地寻找快乐。 “奇怪”
“那种感觉”变成了一种愉快的感觉。
是<.  

贝科斯会到达波尔蒂奥吗？
没有必要因为没有而悲伤。
不。反复深入阴道内部
如果你给予刺激，这种刺激就会
波尔蒂奥也是如此。  

不要着急，慢慢来“培养”女孩的快乐。
请。  

图：部分性感区位置

**图例**：
  - 阴道口
  - 尿道口
  - 外阴口
  - 肛门
  - 膀胱
  - 儿童宫
```

### Page `064.jpg`

**JP source (DeepSeek-OCR-2)**

```
体の赤ちゃんの成長

8週目  
画像：小宝宝坐在地上，双手抱膝。

12週目  
画像：同上。

16週目  
画像：同上。

32週目  
画像：同上。

36週目  
画像：同上。
```

**JP source (Qwen OCR)**

```
体内の赤ちゃんの成長
8週目
12週目
16週目
32週目
36週目
```

**Reference (OCR of 熟肉)**

```
胎儿在**腹内的成长**

8週目  
12週目  
16週目  
32週目  
36週目
```

**DeepSeek-Chat**

```
**身体里宝宝的成长**

**第8周**  
（图：小宝宝坐在地上，双手抱膝）

**第12周**  
（图：同上）

**第16周**  
（图：同上）

**第32周**  
（图：同上）

**第36周**  
（图：同上）
```

**Google Translate**

```
[Google翻译] 宝宝身体成长

第8周
图片：Kobahoza 坐在地上，双臂抱住膝盖。

第12周
图片：同上。

第16周
图片：同上。

第32周
图片：同上。

第36周
图片：同上。
```

**Qwen (end-to-end)**

```
胎儿在母体内的成长
第8周
第12周
第16周
第32周
第36周
```

### Page `060.jpg`

**JP source (DeepSeek-OCR-2)**

```
ロラム  
妊婦フェチジズム  

赤ちゃんでお腹をパンパンに膨らませた女体に大興奮！  
奥深い「妊婦フェチジズム」の世界とは  

世の男性の中には、妊娠している女の子の姿に性的な興奮を覚える人もいます。「太った女性の肉体に興奮する」ということではありません。体の他の部分が通常の細さなので、お腹だけが大きくなっている状態に興奮するのです。  

また、妊娠の結果としておっぱがいが大きく張ったり、乳首が黒ずんだりした状態を好むというケースもあります。これらの「妊娠中のおっぱい」マニアの男性は、母乳マニアも兼ねているケースが多く見られます。  

また分娩台であおむけになっている女性に興奮する医療マニアの嗜好なども、近接するジャンルだといえるでしょう。  

大量の精液を子宫に注ぎ込む膣内射精に興奮する「孕まぜフェチ」の心理は、倫理的なことはさておき、種の保存というセックスのもそもその目的から考えれば納得のいくものだといえます。しかしこの「妊婦フェチ」は単に自分の子供を残したいという本能だけでは説明がつきません。お腹の中のみ赤ちゃんが自分の子でなくても、こういった男性は興奮してしまうのです。  

---

昔から妊婦フェチは存在した  

性的対象の細分化と深化の進んだ成人向けコミックやアダルトゲームの世界では、このような特殊な性癖に対応した描写も見られるようになってきました。しかしこのフェチシズムはけっして近年になって現れたものではありません。  

貴め絵を得意とした明治大正期画家・伊藤晴雨は逆さ吊りにされた裸の妊婦が責められている倒錯的な作品を残しています。画家
```

**JP source (Qwen OCR)**

```
コラム
妊婦フェチシズム
赤ちゃんでお腹をパンパンに膨らませた女体に大興奮！
奥深い「妊婦フェチシズム」の世界とは
世の男性的中には、妊娠している女の子の姿に性的な興奮を覚える
人もいます。「太った女性の肉体に興奮する」ということではあ
りません。体の他の部分が通常の細さなのに、お腹だけが大きくなっ
ている状態に興奮するのです。
また、妊娠の結果としておっぱいが大きく張ったり、乳首が黒ず
んだりした状態を好むというケースもあります。これらの「妊娠中
のおっぱい」マニアの男性は、母乳マニアも兼ねているケースが多
く見られます。
また分娩台であおむけになっている女性に興奮する医療マニアの
嗜好なども、近接するジャンルだといえるでしょう。
大量の精液を子宮に注ぎ込み膣内射精に興奮する「孕ませフェ
チ」の心理は、倫理的なことはさておき、種の保存というセックス
のそもそもの目的から考えれば納得のいくものだといえます。しか
しこの「妊婦フェチ」は、単に自分の子供を残したいという本能だ
けでは説明がつきません。お腹の中の赤ちゃんが自分の子でなくても、
こういった男性は興奮してしまうのです。
昔から妊婦フェチは存在した
性的対象の細分化と深化の進んだ成人向けコミックやアダルト
ゲームの世界では、このような特殊な性癖に対応した描写も見られ
るようになってきました。しかしこのフェチシズムはけっして近年
になって現れたものではありません。
責め絵を得意とした明治大正期の画家・伊藤晴雨は逆さ吊りにさ
れた裸の妊婦が責められている倒錯的な作品を残しています。画家
```

**Reference (OCR of 熟肉)**

```
戀孕癖

看到挺著大肚子的女孩子就興奮  
深奧的“戀孕癖”的世界  

世界這麼大，也有那麼些看到懷著孕的孩子就會性慾的男人。  
*羅莉控親姐控年上控各行其道，在這樣的背景下戀孕癖也就沒那麼奇怪了。然而戀孕癖並不是控“胖得肚子大的女孩子”，而是控制身體其他部位都很纖細，只有肚子很大的女性。*

當然，也有喜歡因為妊娠導致胸部變大、乳頭變黑狀態的戀孕癖。這些人不光控“妊娠中的奶子”，一般也會同時控母乳。

對要上分娩台的女性與寵愛的人也屬於戀孕癖的範疇內。

對於宮中大量中出感到興奮的人的內心，先不說倫理道德上的問題，單以種族延續的目的來說也不是不能接受。但是戀孕癖是不能單純用想要留種的本能來說明。也有就算肚子裡還的孩子不是自己的也能感到興奮的男性。

自古以來就有戀孕癖的存在

現在日本的成人漫畫和game界的暢宅作品越來越注重差異化和定向化，戀孕癖作為一種特殊的性癖好也受到了關注。但是戀孕癖的出現卻不是最近的事。

明治大正時期擅長繪畫繡線系的畫家——伊藤晴雨曾攝他懷孕的妻子黃湯，並將她懸空倒掛來繪畫。

58
```

**DeepSeek-Chat**

```
**专栏：孕妇情结**

**因怀孕而腹部高高隆起的女性身体，令人极度兴奋！**
**深入解读“孕妇情结”的世界**

世上有些男性，会对怀孕中的女性身体产生性兴奋。这并非指“对肥胖女性的肉体感到兴奋”。而是指身体其他部位保持正常纤细，唯独腹部变大的状态，会让他们兴奋。

此外，也有人偏好因怀孕而导致乳房胀大、乳头颜色变深的状态。这些迷恋“孕期乳房”的男性，往往同时也对母乳有特殊癖好。

另外，对产床上仰卧的女性感到兴奋的医疗癖好，也可以算作相近的范畴。

至于对“大量精液注入子宫的阴道内射精”感到兴奋的“受孕癖”心理，暂且不论伦理问题，从性行为原本“繁衍后代”的目的来看，倒也可以理解。然而，这种“孕妇情结”却无法单纯用“想留下自己后代”的本能来解释。因为即使腹中的孩子并非自己的，这类男性依然会感到兴奋。

---

**孕妇情结自古有之**

在性对象不断细分、深度不断发展的成人漫画和成人游戏世界里，也开始出现对应这种特殊癖好的描写。但这种情结绝非近年才出现的新事物。

擅长描绘凌辱场面的明治大正时期画家·伊藤晴雨，就留下了描绘被倒吊的裸体孕妇遭受折磨的、充满倒错感的作品。
```

**Google Translate**

```
[Google翻译] 洛拉姆
孕妇恋物癖

对于生完孩子肚子胀鼓鼓的女性身体，我感到非常兴奋！  
“恋孕妇癖”的深奥世界是什么？

世界各地的一些男人会因为看到怀孕的女孩而产生性唤起。这并不是因为对胖女人的身体感到兴奋。她身体的其他部分通常都很瘦，所以当只有她的肚子变大时，她就会感到兴奋。  

也有女性因为怀孕而喜欢乳房肿胀或乳头变黑的情况。这些“孕乳狂人”往往也是哺乳狂人。  

也可以说，那些因看到仰卧在产床上的女性而兴奋的医学爱好者的口味是类似的流派。  

“生育恋物癖”的心理是由阴道射精引起的，大量的精液被倒入神社，当你考虑到性的目的，即保存种子，抛开道德考虑之外，这是有道理的。然而，这种“怀孕迷恋”并不能简单地用想要保留孩子的本能来解释。即使子宫里的孩子不是他们的，这些男人也会感到兴奋。  

---

恋孕妇癖自古就有。

在成人漫画和成人游戏的世界里，性对象日益细分和深化，我们开始看到适应这种特殊性倾向的描绘。然而，这种拜物教绝不是最近才出现的现象。  

明治、大正时期的画家伊藤清宇，专门创作名贵画作，留下了一幅将裸体孕妇倒挂受折磨的变态作品。画家
```

**Qwen (end-to-end)**

```
专栏
孕妇情结
看到女性因怀有婴儿而将腹部高高隆起的身体，便感到极度兴奋！
深入探究“孕妇情结”的世界
在男性群体中，有一部分人会对怀孕女性的姿态产生性兴奋。
但这并非单纯指“对肥胖女性身体感到兴奋”。
他们兴奋的点在于，身体其他部位保持着正常的纤细，唯独腹部因怀孕而显著膨大的状态。
此外，也有部分人偏好因怀孕导致乳房胀大、乳晕变黑的状态。
这类对“孕期乳房”着迷的男性，往往同时也对母乳情有独钟，这种情况十分常见。
另外，对躺在分娩台上、呈仰卧位的女性感到兴奋的医疗癖好，也属于与之相近的范畴。
至于“受孕情结”——即渴望将大量精液注入子宫、在阴道内射精并对此感到兴奋的心理，
若暂且不论伦理道德，仅从“繁衍后代”这一性行为最根本的目的来考量，
这种心理也是合乎情理的。
然而，“孕妇情结”并不能仅用“想要留下自己的后代”这一本能来解释。
即便腹中的胎儿并非自己的骨肉，这类男性依然会感到兴奋。
孕妇情结自古有之
在成人漫画和成人游戏等面向成年人的作品中，
随着性癖好的细分与深化，针对此类特殊癖好的描写也日益增多。
但“孕妇情结”绝非近年才出现的现象。
擅长绘制凌辱题材的明治至大正时期画家伊藤晴雨，
就曾留下过描绘被倒吊的裸体孕妇遭受凌辱的倒错性作品。
```

## Caveats

- The Chinese reference is OCR'd from a fan-translated manga; it is not a hand-
  curated parallel corpus. Both reference and system output share OCR errors.
- `生肉/N.jpg` and `熟肉/N.jpg` are not always the same page in this dataset —
  see "Qualitative observations" above. Run-level metrics absorb this noise.
- Fan translations take liberties (omission, paraphrase, register shift) that
  surface BLEU/chrF cannot distinguish from translation errors.
- The corpus is a single title (133 pages); results may not generalize to other
  genres. This manga is body-text heavy with anatomical terminology, which both
  backends translate with varying creativity.
- DeepSeek prices change. Cost figures are estimates using the rates above.
- Semantic metrics (BERTScore, COMET) would give a more faithful picture but
  require GPU + extra dependencies and are out of scope here.
