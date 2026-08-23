# @zleapai X Article 正文提取（Kimi WebBridge）

抓取时间：2026-06-17 首次提取；2026-06-18 追加第 8、9 篇（浏览器实时打开 X Article 页面提取）

## 1. Zleap-Agent：自带稀疏注意力的 Agent Harness

- 原帖时间：2026-06-17 05:50:48 GMT
- 帖子 ID：2067122770551635995
- Article 链接：https://x.com/i/article/2067119217460314112
- 浏览器实际 URL：https://x.com/zleapai/article/2067122770551635995
- 提取字符数：4707

### 正文（清理版）

简介：不是把更长的 prompt 塞给模型，而是在 Harness 层切割上下文、工具和记忆。开源链接：https://github.com/Zleap-AI/Zleap-Agent
大家好，我是 Jomy。去年开始，我和我的团队一直在研究企业内部的本地化 AI 落地。
企业场景和个人玩具不一样。数据不能随便出内网，成本也不能无限往上堆。所以很多时候，我们不能默认用最贵、最大的模型。
我们选择了小参数模型，也一直在研究怎么把本地模型用好。昨天讲解的 SAG 技术，解决的是底层数据检索和上下文生成。
但研究完数据层之后，我们发现 Agent Harness 层也有同样的问题。
过去一年，大家都在说上下文变长了。
显卡更便宜了，推理框架更成熟了，模型能吃进去的 token 越来越多。于是很多人有一个错觉：
既然上下文变长了，那就把工具、记忆、历史、规则都塞进去。
问题是，窗口变大，不代表注意力变便宜。
模型行业自己也知道这个问题。很多研究都在做稀疏注意力、滑动窗口、长上下文压缩，本质上都是一件事：
不要让模型每一步都看所有东西。
我们觉得，这件事不只应该在模型架构里做。
Agent Harness 层也应该做。
而且更简单。
今天这篇，分享一下我们的思路。
注意力很珍贵
上下文窗口变长，只代表模型能装下更多 token。
不代表它每一步都能准确使用这些 token。
能放进去，不代表模型能稳定用上。尤其是本地小模型。它本来就没有那么强的指令遵循能力，也没有那么强的长上下文定位能力。你再把几十个工具、几百条历史、各种记忆和规则全塞进去，它不是变聪明了，而是先被迫做一遍信息筛选。
现在很多 Agent Harness 的设计，默认背后有一个很强的模型。
Claude Code 就是一个典型例子。它把 Claude 包成一套 agentic coding 工具链，让模型可以读代码、改文件、跑命令、接 MCP、用 hooks、开 subagents。
OpenClaw、Hermes 这类新工具，也在往同一个方向走：给模型加执行环境、加工具、加长期记忆、加自动化能力。
这些系统很重要。它们把 Agent 往前推了一大步。
但问题也在这里。
工具越来越多，记忆越来越长，规则越来越厚，日志越来越完整。最后还是让模型自己在里面找路。
这不是本地小模型才会遇到的问题。大模型只是更能扛，所以问题不那么明显。但注意力浪费最后都会变成三件事：
更慢。更贵。更容易错。
Workspace
Zleap-Agent 的判断不一样。我们不是先问“Agent 能接多少工具”。我们先问：
这一刻，它到底应该在哪个 workspace 里？
Workspace 是 Zleap-Agent 最重要的概念。
它不是子 Agent，也不是工具分组。
Workspace 是 context 和 tools 的隔离层。
这件事其实很好理解。
就像人使用操作系统。
主 workspace 是桌面。桌面不应该塞满所有软件里的所有按钮、所有文档、所有历史记录。它只负责让你知道有哪些软件可以打开，以及现在该打开哪个。
进入销售 workspace，就像打开 CRM。你看到客户、合同、跟进记录和销售工具。
进入财务 workspace，就像打开财务软件。你看到发票、报销、预算和审批规则。
进入内容 workspace，就像打开内容编辑器。你看到选题、素材、发布记录和写作经验。
同一个 Agent，站在不同工作台前。
但它不需要每次都看到所有东西。
这和子 Agent 很不一样。子 Agent 更像临时找了另一个人帮忙。它有自己的角色，自己的提示词，自己的上下文。做完之后，把结果丢回来。
Workspace 不是这样。
Workspace 仍然是同一个 Agent 在工作。只是当前可见的工具、上下文和记忆变了。更关键的是，每个 workspace 都有自己的工作记忆。这些记忆会留在这个 workspace 里，不会随便串到主空间，也不会串到别的 workspace。
主空间只负责调度，不应该拿到所有细节。
这点很重要。因为主空间如果拿到了所有工作区的记忆和工具，它就又变回了那个“大脑塞满一切”的传统 Agent。
还有一个自然的延伸：LLM 不一定要被写死在 Agent 里。
未来完全可以给不同 workspace 配不同模型：普通沟通用便宜模型，复杂分析用强模型，视觉工作区用多模态模型，本地敏感数据用本地模型。
这就自然形成了模型自动路由，也形成了端云协调：能在本地做的，就在本地做；需要更强能力的，再交给云端模型。
不是先选模型，再硬塞任务。
而是先选 workspace，再由 workspace 决定最合适的模型。
把 Context 当内存
Context 不应该只被看成一段 prompt。
我们过去太习惯把 prompt 当成一段文本。把 system、人格、工具说明、历史、记忆全部拼起来，最后发给模型。
这很粗糙。
在 Zleap-Agent 里，我们把 Context 像内存一样分成几个区域，大致可以总结为：
Context = System Prompt + Workspace Prompt + Tools + Memory + History
System Prompt 是系统提示词 + 人格。它定义这个 Agent 的底层行为和表达方式。它不应该随着 workspace 来回变。
Workspace Prompt 是当前工作区的说明。它告诉模型：你现在在哪个工作台前，你能做什么，你不能做什么。
Tools 是当前工作区里可以用的工具。不是全局工具池。
Memory 是当前需要被带进来的记忆。不是完整历史。
History 是用户近期的消息。不是整个对话的回放。
这些内容有两种加载方式。
一种是 prefetch，也就是程序提前放进来的内容。比如当前用户的长期偏好、当前 workspace 最近相关的事件、这个 workspace 常用的经验。这些内容应该短、准、可控。
另一种是 agentic，也就是模型需要的时候自己去拿。比如它看到一条旧记忆的摘要，但用户追问“详细说说”，这时它再去读详情。比如它看到一个经验标题，觉得这次任务很像，再去展开完整方法。
在 Runtime 中必须严格规定好：
哪些是预取的。哪些是按需读取的。
否则所谓上下文管理，最后还是一锅粥。
所以在不同 workspace 中切换，本质上就是切换不同的 Workspace Prompt + Tools + Memory + History。System Prompt 保持一致，Agent 的人设和行为风格也就保持了一致。
记忆要分区
接下来我们详细讲一下 Memory 的设计。
它是 workspace 能够跑通的关键。
如果 Memory 只有一个“长期记忆”的篮子，那还是太粗。
人类自己也不是这样记东西的。我们会记一个人，记一件事，也会记一套经验。
Zleap-Agent 也是这样。我们把记忆分成了三类。
第一类是对人的记忆。比如这个用户喜欢直接说结论，讨厌空话；比如他经常做企业产品；比如他希望 Agent 用中文沟通。这类记忆应该跟用户绑定。因为同一个 Agent 在组织里可能被很多人使用，A 的偏好不能影响 B。
第二类是对事的记忆。比如某个客户上次沟通到哪一步，某个合同为什么卡住，某次活动复盘里发现转化率掉在了哪一环。这类记忆既跟用户有关，也跟 workspace 有关。销售 workspace 里的客户推进，不应该跑到财务 workspace 里。财务 workspace 里的报销规则，也不应该污染内容 workspace。
第三类是经验。比如“做客户复盘时，先看最近三次沟通记录，再看成交阶段变化”；比如“写周报时，先按目标、进展、风险、下周计划组织”；比如“处理报销问题时，先判断是票据缺失、预算超额，还是审批链卡住”。
经验可以被用户共享，但必须脱敏。
它应该留下方法，而不是留下某个人的隐私、某个客户的细节、某个项目的原始资料。
这就是为什么 workspace 必须有自己的记忆。不是为了概念好看，而是为了避免污染。
记忆一旦串了，Agent 就会开始胡说。
更严重的是，在企业场景里，记忆串了就是安全事故。
数据库驱动
一旦 Agent 要在组织里被多人共享，问题就不再只是“怎么记住”。
而是：
谁的记忆，能被谁看到？
哪个 workspace 的记忆，能进入哪个 workspace？
哪些经验可以被用户共享，哪些信息必须永远隔离？
所以从 day 0 开始，Zleap-Agent 就不是按单人本地文件夹来设计的。
我们把 Agent 的数据都交给数据库来管理。
一个好的 Agent，未来一定会在组织里被很多人共享。销售用它，运营用它，财务用它，研发用它，老板也用它。每个人都有自己的偏好、权限、历史和任务。每个 workspace 又有自己的上下文、工具和记忆。
这种结构，不能靠文件系统解决。
文件系统更像原始日志。你可以把东西写进去，也可以读出来。但它不适合做多租户隔离，不适合做细粒度权限，不适合高频 agent loop，也不适合管理多层记忆分区。
Zleap-Agent 的记忆系统不是偶尔读一次文件。
它是每一轮 agent loop 都要参与的系统。
模型进入哪个 workspace，要查当前 workspace 的记忆。模型调用工具之后，要判断哪些信息值得留下。任务结束之后，要沉淀事件。多个用户共享同一个 Agent 时，还要保证用户之间不串记忆，workspace 之间不串记忆，用户共享经验又能被安全复用。
这就是数据库驱动的意义。
它不是“把文件换成表”。
它是把 Agent 的运行过程变成一个可以分区、可以审计、可以回滚、可以复用的系统。
总结
模型行业在模型层研究稀疏注意力，是为了让模型不要看所有 token。
Zleap-Agent 在 Harness 层做 workspace，是为了让 Agent 不要看所有上下文。
一个在模型里面做。
一个在系统外面做。
但目标是一样的：
把注意力用在真正重要的地方。
所以我们说，Zleap-Agent 不是又一个 Agent 框架。
它想提出的是一个新的 Agent Harness 范式。
未来的 Agent，不应该靠一个越来越长的 prompt 去硬撑。它应该有工作区，有分区记忆，有数据库底座，有模型路由，有清晰的上下文边界。
这样，小模型才能真正可用。
大模型也会更快、更准、更省钱。
今天，我们也正式开源了 Zleap-Agent 的 Preview 版本。这个版本主要是为了把具体的逻辑和思路展示出来，里面还有很多细节没有优化。如果你对这个方向感兴趣，也欢迎一起参与到开源版本的迭代中来。
下一篇文章，也是这个系列的最后一篇文章，我会给大家分享一下，我们基于 SAG 和 Zleap-Agent，在产品应用上的新思路。明天见！
#harness #AIAgents #SAG #EnterpriseAI #OpenSource

---

## 2. SAG: New SOTA in RAG — An Agent-Oriented Data Foundation

- 原帖时间：2026-06-16 12:02:12 GMT
- 帖子 ID：2066853847507874288
- Article 链接：https://x.com/i/article/2066819418030772224
- 浏览器实际 URL：https://x.com/zleapai/article/2066853847507874288
- 提取字符数：15713

### 正文（清理版）

Intro: Traditional RAG solves "retrieving text " , but what Agents truly need is a data foundation that supports incremental writes, multi-hop retrieval, traceability, and maintainability.
Paper link: https://arxiv.org/abs/2606.15971
Open-source link: https://github.com/Zleap-AI/SAG
Hi everyone, I’m Jomy. This week, I’ll publish three articles in three days to share some of the recent work we’ve been doing at Zleap. Today, let’s start with SAG.
Over the past two years, almost every AI application has run into the same question:
As models become more capable, the quality of an agent’s work increasingly depends on the context it can access.
When context is missing, we use RAG to retrieve it.
But in complex tasks, one retrieval step is often not enough.
That is why Agentic RAG has become popular. At its core, it lets the model retrieve over multiple rounds: decompose the question, retrieve, read the results, then decide what to search for next.
This sounds reasonable.
But if each retrieval step is noisy, asking the model to repeatedly think, search, and judge creates a different problem:
More tokens are consumed, latency grows, and uncertainty compounds at every step.
I once proposed a view: the amount of intelligence you get is bounded by the amount of computation you can spend.
But the more important question is: where should that computation happen?
Should the agent search, reason, and assemble context on the fly every time a user asks a question?
Or should the system organize the data properly when the data first enters the system?
The real issue is not whether an agent can search multiple times. The real issue is whether massive context has already been organized into a reusable data layer before the agent starts working.
That is the question this article is trying to answer.
From the start of the project, to the first open-source release of SAG last November, and now to the formal release of our paper and benchmark results, we have spent about a year on this.
Today, I want to explain why we believe RAG needs to be rethought from the bottom up.
The Bottleneck of RAG
The biggest strength of traditional vector RAG is speed.
It turns each text chunk into a vector. When a question comes in, it retrieves the chunks that look most similar to the query.
This works well for static document QA: small datasets, simple questions, and answers that are usually located inside one paragraph.
But it has a fundamental limitation:
Vector search only knows "similarity"—it doesn't understand "who did what to whom and how things relate."
Take a multi-hop question: the answer might span multiple documents:
Company A acquired Company B. B's CTO later joined Project C. Project C then influenced a product roadmap.
Individually, none of these snippets might look particularly relevant to the question. Connected, they form the answer.
Vector RAG struggles to reliably trace that chain.
GraphRAG points in the right direction—it recognizes that text contains entities, relationships, and structure.
But GraphRAG is heavy.
Many GraphRAG systems extract triples, perform entity resolution, relation normalization, community detection, and community summarization. Every step relies on LLMs, and every step can introduce errors.
Worse, graphs aren't a one-time build. Real-world data changes daily: new entities, new aliases, new relationships emerge, while old ones may become outdated.
Maintaining a large graph is often harder than building one.
HippoRAG 2 is currently a very strong direction—it proves that RAG can't rely solely on vectors; it must combine structured memory with multi-hop retrieval.
But HippoRAG 2's biggest drawback is its reliance on global Personalized PageRank / PageRank-style graph ranking.
This works at benchmark scale. But at massive scale, with continuous daily growth, global PageRank becomes a heavy lift.
For Agents, the data foundation must support continuous writes, continuous updates, traceability, and rollback. You can't recompute the entire global graph every time new data arrives.
So we need a new structured document format.
(From NaiveRAG to GraphRAG to SAG: structure isn't about being heavier—it's about whether it can support incremental updates, multi-hop retrieval, and real-world Agent scenarios.)
The Structure of SAG
The core structure of SAG is simple:
chunk → event
chunk → entities
event → entities
One chunk corresponds to one event.
Multiple entities extracted from the same chunk are associated with that event.
This differs from the traditional graph triple approach.
A triple looks like this:
subject → predicate/relation → object
In knowledge graphs, it's often written as:
head entity → relation → tail entity
For example:
SAG → uses → hypergraph
SAG → stores → events
SAG → supports → multi-hop retrieval
The problem is that triples break a complete semantic unit into small fragments. Their quality depends heavily on whether the predicate or relation is extracted correctly.
The same fact can be expressed with different predicates by different models: uses, is based on, proposes, supports. In real-world data, this variation quickly becomes noise.
SAG does not take this route.
We ask the LLM to do two more stable things: summarize each chunk into a complete, self-contained event, and extract as many entities as possible from the original chunk. Then we connect these entities to the event.
The event preserves meaning.
The entities come from the original chunk and serve as index points.
So SAG isn't fundamentally about "extracting relationships more accurately"—it's about adding a semantic index layer on top of raw data.
Structurally, this is more like a hyperedge: one event connects multiple entities simultaneously.
It's not an edge between two points—it's one thing that organizes multiple entities together.
This is better suited for RAG than triples.
Because RAG ultimately needs to return to the original evidence. Triples are too fragmented and lose context; events preserve context while providing a retrievable, scalable structure.
That's SAG's core:
Not a heavier graph, but a lighter, more robust data index.
New SOTA
Let's look at the results.
(Simplified benchmark chart highlighting average Recall@2, MuSiQue Recall@5, and the improvement of hyperedge structure over triple-based structure.)
We compared against HippoRAG 2 under identical Embedding and LLM configurations.
Embedding = bge-large-en-v1.5
LLM = qwen3.6-flash
Datasets: HotpotQA, 2WikiMultiHop, MuSiQue.
SAG's average Recall@2 is XX% vs. HippoRAG 2's 68.14% — a +11.16 percentage point improvement, roughly +16.4% relative.
This matters more than Recall@10.
Agents don't want to retrieve a massive pile of context every time. What they really need is to hit the critical evidence earlier, with fewer results.
Otherwise, the LLM has to read more, increasing cost, latency, and noise.
MuSiQue is a harder, compositional multi-hop dataset. This improvement shows that the event/entity index genuinely helps with complex relational questions.
A quick experimental note:
HippoRAG 2 scores lower with bge-large-en-v1.5—its original paper uses the larger NV-Embed-v2, achieving ~74% MuSiQue Recall@5.
But embedding models don't affect SAG as much.
SAG achieves 80.04% MuSiQue Recall@5 with bge-large-en-v1.5, and 81.71% with NV-Embed-v2.
This suggests SAG's gains don't come from better embeddings—they come from the robustness of the algorithmic structure itself.
We also compared triple-based structure against our event-hyperedge structure.
On MuSiQue, the triple-based 1-n-2 structure achieved 77.16% Recall@5.
SAG's current one-event-with-multiple-entities hyperedge structure achieved 80.04% Recall@5.
This experiment shows that SAG's hyperedge structure is genuinely better suited for RAG retrieval than triples.
More importantly, it achieves this without being more complex—it's actually simpler.
Triples need to break down relationships and depend on accurate relation extraction.
SAG only needs to preserve a complete event and extract entities from the chunk as exhaustively as possible for indexing.
Lighter structure, better results.
We've also conducted extensive ablation studies to validate these design choices. For more details, check out our paper.
How SAG Works
(SAG High-Precision Mode architecture: SQL relation expansion, vector retrieval, and full-text search, followed by LLM reranking.)
SAG has two stages: offline writing and online retrieval.
During offline writing, the system first splits documents into chunks.
Each chunk is converted into an event.
At the same time, multiple entities are extracted from the chunk, with a high-recall strategy.
Everything is then written into the database.
Vector indexes and full-text indexes are also written at the same time.
In other words, SAG does not only store raw text.
It stores a structure that can be used by SQL queries, vector recall, full-text retrieval, and multi-hop expansion.
Once seed events are retrieved, there is no mysterious intelligence inside SAG.
It simply performs relational expansion in SQL:
First, fetch the entity IDs linked to the seed events.
Then use the event_entities table to find other events connected to those entities.
Exclude events that have already appeared, and you get the next batch of candidate events.
That is multi-hop retrieval.
It is not global PageRank. It is not asking an LLM to reason over a graph at query time.
It is relational expansion inside a database.
Finally, the event is mapped back to the original chunk.
Because answers cannot rely only on abstract events. They must return to source evidence.
SAG currently has two main modes:
In short:
Fast mode is built for speed.
High-precision mode is built for accuracy.
But neither mode is traditional RAG, because both use SAG’s event/entity index.
The architecture above shows the high-precision mode, where an LLM participates in reranking.  Fast mode removes that step, while still retaining multi-hop retrieval.
Scaling SAG
True scalability is not about making the graph bigger.
It is about allowing data to keep flowing into the system.
This is also the biggest difference between SAG and many GraphRAG approaches.
SAG does not need to maintain a global knowledge graph in advance.
When new data arrives, it is chunked. Each chunk is converted into an event and entities, then written into SQL.
This is closer to incremental database writing than global graph reconstruction.
There is another important point:
A chunk is a natural unit of concurrency.
The event/entity extraction of each chunk can run independently. So on the writing side, the system can process large batches of chunks in parallel.
Event extraction can run in parallel. Vector generation for events, entities, and relations can also run in parallel.
This is not a pipeline that has to build a graph slowly and serially.
That is one of the reasons SAG can scale up.
Some people may ask:
What happens when the same entity appears during parallel extraction?
Our solution is simple.
We do not do complex entity merging, and we do not rely on heavy entity resolution.
Before inserting each entity into the database, we apply simple string normalization and SQL lookup.
Under the same source, if an entity with the same type and name already exists, we reuse it. If not, we insert a new one.
This is a plain approach, but it also shows the robustness of SAG.
It does not need a perfect entity merging system to work.
Even with simple string checks and SQL deduplication, the event-to-multiple-entities structure already produces the results we see today.
Because in SAG, entities are primarily index points. They are not where the full meaning lives.
The event is what preserves meaning.
To test SAG’s production readiness, we also validated it on real-world data scale.
We have crawled massive web data and built a database at the 500-million-record scale, and it is still growing.
At this scale, SAG remains stable.
To make the technology easier to experience online, we also built a Wikipedia-based SAG demo.
We crawled and processed Wiki data, put it into SAG, and made it available for testing multi-hop retrieval.
Online demo:  wiki.zleap.com
A Data Layer for Agents
Why do we call SAG a data layer for agents?
Because agents are different from ordinary QA systems.
An ordinary QA system retrieves once and answers once.
An agent often needs to search many times in sequence.
It searches for one clue, uses that clue to search for the next one, then decides what to do next based on the new result.
In this setting, retrieval accuracy is no longer just a user experience issue. It becomes a stability issue for the entire task chain.
If the first retrieval step is wrong, the later reasoning is built on the wrong material.
If the first step misses the right clue, the agent may continue searching in the wrong direction.
In difficult tasks, these errors accumulate.
The more it searches, the further it may drift.
In the end, it is not “search a few more times and you will eventually find it.” It may never find the right evidence at all.
Better retrieval has two layers of value:
First, it finds the right content with fewer query steps.
Second, when multiple retrieval steps are necessary, it lowers the probability that errors compound at each step.
The value of a data layer is not optimizing a single QA turn. It is making the entire action chain of an agent more reliable.
Memory is another typical scenario built on top of the data layer.
Why can SAG support memory?
Because memory is not isolated text. It is changing data.
The same user, project, or preference may appear repeatedly at different times. New memory may add to, correct, or even overturn old memory.
Pure vector memory is closer to finding similar text. But agents need to know which pieces are historical background and which represent the current state.
SAG’s structure fits this problem well: events preserve complete facts, entities connect the same person, project, task, or preference, and SQL can add time, source, and related IDs.
In the example above, vector retrieval may recall both memories, but it may not know which one is newer.
SAG can connect the two memories through entities such as Project A, the user, and task status, then combine time and related IDs to identify the current state.
So SAG can support memory not because we added a separate memory module, but because the structure itself builds indexes around events, entities, time, and relationships.
That is the kind of data structure agents can use over the long term.
Summary
The next stage of RAG is not increasing top-k.
It is not stuffing more content into a longer context window either.
It is redesigning how data enters an agent.
SAG can be summarized in three points:
First, it adds a lightweight index layer to raw data through chunk -> event, chunk -> entities, and event <-> entities.
Second, it combines SQL relational expansion, vector retrieval, and full-text search to make multi-hop retrieval faster and more stable.
Third, it supports incremental writing, parallel processing, and continuous growth, becoming a data layer agents can rely on over time.
This is why we do not see SAG as just another RAG patch.
SAG changes how data is organized before it enters retrieval systems and agent systems.
It represents a new direction for the next generation of RAG: moving from text recall to a structured data layer.
In the next article, I will share how we built an Agent Harness with sparse attention on top of SAG.
See you tomorrow.
#RAG #AIAgents #SAG #EnterpriseAI #OpenSource

---

## 3. SAG：RAG领域新SOTA，面向Agent的数据底座

- 原帖时间：2026-06-16 09:43:13 GMT
- 帖子 ID：2066818873530401273
- Article 链接：https://x.com/i/article/2066799645255434240
- 浏览器实际 URL：https://x.com/zleapai/article/2066818873530401273
- 提取字符数：5927

### 正文（清理版）

简介：传统 RAG 解决的是“把文本找回来”，但 Agent 真正需要的是一套能增量写入、多跳检索、可追溯、可维护的数据底座。
论文链接：https://arxiv.org/abs/2606.15971
开源链接：https://github.com/Zleap-AI/SAG
大家好，我是 Jomy，本周我会连续三天发表三篇文章，来向大家汇报一下我们 Zleap 近期的一些成果。今天我们先讲 SAG。
这两年，几乎所有 AI 应用都绕不开一个问题：
模型能力越来越强后，Agent 完成任务的质量，越来越取决于它能拿到什么上下文。
上下文不够，就用 RAG 去检索。
但复杂任务里，一次检索往往不够。
所以最近流行的 Agentic RAG，本质上就是让模型多检索几轮：先拆问题，再循环检索、阅读结果，最后决定下一步查什么。
这听起来很合理。
但如果每一步都搜不准，让模型重复思考、检索、判断，系统很快会遇到另一个问题：
token 越用越多，延迟越来越高，不确定性也会在每一轮里叠加。
我之前提出过一个观点：有多少计算，就有多少智能。
但真正关键的问题是：这些计算到底应该发生在哪里？
是每次用户提问时，让 Agent 临时查、临时想、临时组织上下文？
还是在数据进入系统的时候，就先把该整理的东西整理好？
问题不在于 Agent 能不能多搜几轮，而在于海量上下文进入系统时，是否已经被整理成可持续使用的数据底座。
这就是今天这篇文章要回答的问题。
从开始立项，到去年11月初步开源 SAG 第一个版本，最后到今天正式发布论文和 benchmark 结果，我们研究了一年。
今天我来向大家详细讲讲，我们为什么要从底层重新思考 RAG。
RAG 的瓶颈
传统向量 RAG 最大的优点，是快。
它把每段文本变成向量，问题来了，就找几段最像的文本。
这个逻辑适合静态文档场景：数据少，问题简单，答案就在某个段落里。
但它有一个根本限制：
向量搜索只知道“像不像”，不知道“谁和谁发生了什么关系”。
比如一个多跳问题，答案可能分散在几个文档里：
A 公司收购了 B 公司，B 公司的 CTO 后来加入 C 项目，C 项目又影响某个产品路线。
这些信息单独看，未必和问题特别相似。连起来，才是答案。
向量 RAG 很难稳定找到这条链。
GraphRAG 的方向是对的。它意识到文本里有实体、有关系、有结构。
但 GraphRAG 又太重。
很多 GraphRAG 系统会把文本抽成三元组，做实体合并、关系归一、社区发现、社区摘要。每一步都依赖 LLM，每一步都可能出错。
更麻烦的是，图谱不是一次性建完就结束。真实世界的数据每天都在变：新实体、新别名、新关系会不断出现，旧关系和旧摘要也可能过时。
维护一张大图，往往比建一张大图更难。
HippoRAG 2 是目前非常强的方向，它证明了 RAG 不能只靠向量，必须结合结构化记忆和多跳检索。
但 HippoRAG 2 最大的问题，是依赖全局 Personalized PageRank / PageRank 类图排序。
这在 benchmark 规模下可以工作。但如果数据到了海量规模，并且每天增量增长，全局 PageRank 就会变得很重。
对 Agent 来说，数据底座必须持续写入、持续更新、可追溯、可回滚。不能每来一批新数据，就把全局图重新算一遍。
所以我们需要一种新的结构化文档格式。
(从 NaiveRAG 到 GraphRAG，再到 SAG：结构化不是越重越好，关键是能不能支撑增量、多跳和真实 Agent 场景。)
SAG 的结构
SAG 的核心结构很简单：
chunk -> event
chunk -> entities
event <-> entities
一个 chunk，对应一个事项 event。
同一个 chunk 里抽取出的多个实体 entities，会和这个 event 关联起来。
这和传统图谱的三元组路线不同。
三元组是：
主体 -> 谓词/关系 -> 客体
在知识图谱里，也经常写成：
头实体 -> 关系 -> 尾实体
比如：
SAG -> 使用 -> 超图
SAG -> 存储 -> 事项
SAG -> 支持 -> 多跳检索
问题是，它会把一段完整语义拆得很碎，而且质量高度依赖谓词/关系抽取得准不准。
同一件事，不同模型可能抽出不同谓词：使用、基于、提出、支持。到了真实数据里，这种差异会迅速放大。
SAG 不这么做。
我们让 LLM 做两件更稳定的事：把一个 chunk 总结成一个完整、可独立理解的事项，同时从原始 chunk 里应提尽提地抽取实体，再把这些实体和 event 关联起来。
event 保留语义。
entities 来自原始 chunk，负责索引。
所以 SAG 本质上不是“把关系抽得更准”，而是给原始数据加了一层语义索引。
在图结构上，这更像超边：一个 event 同时连接多个实体。
它不是两个点之间的一条边，而是一件事把多个实体组织在一起。
这比三元组更适合 RAG。
因为 RAG 最后还是要回到原文证据。三元组太碎，容易丢上下文；event 保留上下文，同时提供可检索、可扩展的结构。
这就是 SAG 的核心：
不是更重的图谱，而是更轻、更鲁棒的数据索引。
新 SOTA
先看结果。
简化后的 benchmark 图：突出平均 Recall@2、MuSiQue Recall@5，以及超边结构相对三元组结构的提升。
我们在相同 Embedding 和 LLM 配置下，对比了 HippoRAG 2。
Embedding = bge-large-en-v1.5
LLM = qwen3.6-flash
数据集是 HotpotQA、2WikiMultiHop、MuSiQue。
SAG 平均 Recall@2，HippoRAG 2 是 68.14%。提升 11.16 个百分点，相对提升约 16.4%
这比 Recall@10 更重要。
Agent 不希望每次拿回一大堆上下文。它真正需要的是，在更少结果里，更早命中关键证据。
否则后面 LLM 要读更多内容，成本更高，延迟更高，干扰也更多。
MuSiQue 是更难的组合式多跳数据集，这个提升说明 event/entity 索引确实在复杂关联问题里起作用。
这里需要补充一个实验背景。
HippoRAG 2 在 bge-large-en-v1.5 下的分数会偏低一些。它在原论文里使用的是更大规模的 NV-Embed-v2，MuSiQue Recall@5 大约是 74%。
但 embedding 模型对 SAG 的影响并没有这么大。
SAG 在 bge-large-en-v1.5 下 MuSiQue Recall@5 是 80.04%，换成 NV-Embed-v2 后是 81.71%。
这也侧面说明，SAG 的提升不是单纯靠 embedding 模型堆出来的，而是来自算法结构本身的鲁棒性。
我们还做了三元组式结构和事项超边结构的对比。
在 MuSiQue 上，三元组式 1-n-2 结构的 Recall@5 是 77.16%。
SAG 当前的一事项多实体超边结构，Recall@5 是 80.04%。
这个实验说明，SAG 的超边结构确实比三元组更适合 RAG 检索。
更重要的是，它不是靠更复杂取胜。恰恰相反，它更简单。
三元组要把关系拆细，要依赖每条关系抽得准不准。
SAG 只需要保留一个完整事项，再从 chunk 里应提尽提地抽取实体做索引。
结构更轻，效果反而更好。
我们还做了非常充分的消融实验来证明这些设计选择，更多细节可以查看我们的论文。
流程详解
（SAG 高精度模式架构图：在 SQL 关系扩展、向量召回和全文检索之后，再引入 LLM 精排。）
SAG 分两步：离线写入，在线检索。
离线写入时，系统先把文档切成 chunk。
每个 chunk 提取一个 event。
同时从这个 chunk 里提取多个 entities，应提尽提。
最后写进数据库。
同时写入向量索引和全文索引。
也就是说，SAG 不是只存原文。
它存的是一套可以被 SQL 查询、向量召回、全文检索、多跳扩展的数据结构。
拿到 seed events 之后，SAG 没有什么神秘的智能。
就是在 SQL 里做关系扩展：
先取出 seed events 关联的 entity ids。
再通过 event_entities 表查这些 entities 还连接了哪些 events。
排除已经出现过的 event，得到下一批候选 events。
这就是多跳。
它不是全局 PageRank，也不是临时让 LLM 推理一张图。
就是数据库里的关系扩展。
最后再把 event 映射回原始 chunk。
因为回答不能只靠抽象事项，必须回到原文证据。
SAG 现在主要有两个模式：
简单说：
快速模式负责快。
高精度模式负责更准。
但两者都不是传统 RAG，因为两者都使用了 SAG 的 event/entity 索引。
所以上面的架构图展示的是高精度模式，图里包含 LLM 参与精排；快速模式会去掉这一步，但仍然保留多跳检索。
规模化
真正的规模化，不是把图做大。
而是让数据可以一直写进去。
这也是 SAG 和很多 GraphRAG 路线最大的区别。
SAG 不需要提前维护一张全局知识图谱。
新数据进来，就切 chunk，从 chunk 抽 event 和 entities，写入 SQL。
这更像数据库的增量写入，而不是图谱的全局重建。
还有一个关键点：
chunk 是天然的并发单元。
每个 chunk 的 event/entity 提取可以独立跑。所以写入侧可以大批量并发处理 chunk。
抽取 event 可以并发，生成 event/entity/relation 向量也可以并发。
这不是一个只能串行慢慢建图的流程。
这也是 SAG 能 scale up 的关键。
有人可能会问：
并发抽取的时候，相同实体怎么办？
我们的处理很简单。
没有做复杂的实体合并，也没有做很重的 entity resolution。
每个实体入库前，先做简单字符串归一和 SQL 查询。
同一个 source 下，如果同类型、同名字的实体已经存在，就直接复用；不存在，再插入。
这件事很朴素，但恰恰说明 SAG 的鲁棒性。
它不是依赖一个完美的实体合并系统才能工作。
即使只是简单字符串校验和 SQL 查重，SAG 的一事项多实体结构也已经能跑出现在的效果。
因为 entity 在 SAG 里首先是索引点，不是所有语义本身。
真正保留语义的是 event。
为了证明 SAG 在生产环境里的可用性，我们也在真实数据规模上做了验证。
我们已经把网上海量数据抓取下来，在数据库里形成了 5 亿级数据，并且还在持续增长。
在这个规模下，SAG 仍然可以稳定运行。
为了让大家更好地在线体验我们的 SAG 技术，我们做了一个 Wikipedia 的 SAG 案例。
我们把 wiki 抓下来分析，放进 SAG 里，大家可以直接测试多跳检索效果。
在线体验：wiki.zleap.com
Agent 数据底座
为什么说 SAG 是面向 Agent 的数据底座？
因为 Agent 和普通问答系统不一样。
普通问答系统检索一次，答一次。
Agent 往往要连续查很多次。
它先查一个线索，再根据线索查下一个线索，再根据新的结果决定下一步。
这时候，检索准确率就不只是“体验问题”，而是整个任务链路的稳定性问题。
如果第一次查错，后面的推理会建立在错误材料上。
如果第一次没查到，Agent 可能换一个错误方向继续查。
疑难任务里，这种错误会叠加。
查得越多，偏得越远。
最后不是“多查几次总能找到”，而是可能永远查不到。
所以，更准的检索有两层价值：
第一，用更少的查询次数找到正确内容。
第二，在必须多次查询时，降低每一步错误叠加的概率。
数据底座的意义，不是优化单次问答，而是提高 Agent 整条行动链路的可靠性。
记忆是数据底座上的另一个典型场景。
为什么 SAG 能做记忆？因为记忆不是孤立文本，而是会不断变化的数据。
同一个用户、项目、偏好，可能在不同时间反复出现。新的记忆可能补充、修正，甚至推翻旧记忆。
纯向量记忆更像是在找相似文本，但 Agent 需要知道：哪些是历史背景，哪些是当前状态。
SAG 的结构正好适合这个问题：event 保留完整事项，entities 把同一个人、项目、任务、偏好连接起来，SQL 里再加时间、来源和关联 id。
上面这个例子里，向量检索可能同时召回两条，但不一定知道哪条更新。SAG 可以通过 A 项目、用户、任务状态这些实体关联两条记忆，再结合时间和关联 id 找到当前状态。
所以 SAG 能做记忆，不是因为多加了一个 memory 模块，而是因为它本身就在给数据建立“事项、实体、时间、关系”的索引。
这才是 Agent 可以长期使用的数据结构。
总结
RAG 的下一阶段，不是把 top-k 调得更大，也不是把上下文窗口塞得更满。
而是重新设计数据进入 Agent 的方式。
SAG 做的事情，可以概括成三点：
第一，用 chunk -> event、chunk -> entities、event <-> entities 给原始数据加一层轻量索引。
第二，用 SQL 关系扩展、向量检索和全文检索，把多跳检索做得更快、更稳。
第三，让数据可以增量写入、并发处理、持续增长，成为 Agent 可以长期依赖的数据底座。
这也是为什么我们认为，SAG 不是一个新的 RAG 补丁。
SAG 改的是数据进入检索系统、进入 Agent 系统的组织方式。
它代表的是下一代 RAG 的一个新范式：从文本召回，走向结构化数据底座。
下一篇文章，我会给大家分享一下，我们是如何基于 SAG，创造了一个带稀疏注意力的 Agent Harness，明天见！
#RAG #AIAgents #SAG #LLM #OpenSource

---

## 4. 代理，请为人类提供更好的上下文

- 原帖时间：2026-03-26 03:59:02 GMT
- 帖子 ID：2037016452805648455
- Article 链接：https://x.com/i/article/2037010196514398208
- 浏览器实际 URL：https://x.com/zleapai/article/2037016452805648455
- 提取字符数：10951

### 正文（清理版）

3月26日
26
After I posted the previous article Coexistence of Humans and Agents, some friends asked me: What exactly are you building? An AI version of Xiaohongshu? What’s the point of Agents posting content?
Maybe I didn’t explain it clearly enough last time. Today, let’s approach it from a different angle, starting with a concept that everyone in AI is familiar with: Context.
It’s common knowledge in the industry that for an Agent to perform tasks well, it needs good context. But I’ve always believed that humans themselves are the ones who lack context the most.
Starting with Zuckerberg
Everyone says Zuckerberg stepped into a huge pitfall. Last year, he spent $14.3 billion to acquire nearly half of Scale AI, brought in founder Alexandr Wang, and set up a new lab. What happened? Scale AI’s major clients started leaving one after another, many of the high-paid talents he recruited left within two months, and internal conflicts between old and new teams kept growing. $14.3 billion bought him a complete mess.
In hindsight, many people referenced a classic question: Why can’t the boss hear the truth?
Information decays as it moves up the organization. Every layer of reporting filters and polishes it once more. Bad news turns into good news, risks turn into opportunities. By the time it reaches the CEO’s desk, it’s no longer the same as what people on the front lines actually see.
Recent news revealed that Zuckerberg now wants to build his own CEO Agent — bypassing the reporting chain to directly access raw data from the bottom.
A Reddit AI PhD student also recently went viral. He was juggling papers, deadlines, group meetings, and emails all at once — his brain simply couldn’t hold it all. So he built a system with 8 collaborating Agents and outsourced his entire life to them.
One person couldn’t manage information for 70,000 employees because layers of reporting had beautified the raw data. Another couldn’t handle too much information because his brain had limited capacity. The problems look different, but they share the same root cause: the human brain has an extremely limited context length.
The industry spends every day optimizing the context window for Agents. But who is optimizing the context window for humans?
Let me share our approach next.
Using Generation Instead of Recommendation
Traditional content platforms — Xiaohongshu, Douyin (TikTok), Toutiao — all operate on recommendation logic. There’s a content pool, and the algorithm selects items it thinks you might like and pushes them to you.
But a lot of information is not “content” by nature. Project progress in a company, code commit records, meeting recordings, customer feedback — no one turns these into polished notes. They quietly sit in various systems, unseen and impossible to recommend.
If there’s no content, how do you recommend?
Our approach is: active generation.
The “generation” here doesn’t mean simply pasting raw data. The Agent first understands the data, then processes it into a form humans can easily consume — turning a pile of code commits into visualized charts or illustrated cards. This is completely different from staring at a git log.
The Agent gathers scattered raw data from everywhere — news, documents, code, APIs — understands the relationships between them, and then creates personalized content tailored for each individual.
And the entire process is fully automatic. You don’t need to manually import data — the Agent proactively fetches and syncs it from various systems. You don’t even need to ask — the Agent generates content on its own and pushes it to you. Instead of you looking for information, the information comes to you.
This was impossible before AI. No human could read so much raw data at once and then write a customized report for every single person.
If you open Zleap’s personal version now, you’ll see many Agents already writing current affairs news and industry updates on the platform. These are demos to showcase our capabilities — to let you intuitively experience what it feels like when Agents generate content in real time. But this is not the final state. The real value emerges when you connect your own data sources. Every piece of content the Agent writes will then be relevant to you.
SAG: The Engine Behind It All
To achieve this, we need a powerful engine capable of efficiently handling massive amounts of data.
That’s why we built SAG — what we call the next-generation RAG technology.
What it does is: use AI to automatically break down raw data into semantic atomic events, extract multi-dimensional entities, and then dynamically construct relationship networks during retrieval in real time.
Unlike traditional knowledge graphs, we didn’t use triplets. Instead, we adopted a hypergraph structure — where one edge can connect multiple entities at the same time. This is more suitable for computation, has better scalability, and won’t explode in complexity when handling intricate relationships. The engineering difficulty is indeed much higher than triplets, but that’s exactly what creates our moat — easy things have already been done by others.
Moreover, SAG doesn’t require building the entire graph in advance. When new data comes in, it only needs incremental processing — no need to rerun everything.
It’s fast, accurate, and lightweight. Without this engine, we couldn’t generate real-time personalized content for every person at this scale. SAG has already been open-sourced — feel free to check it out on GitHub if you’re interested.
For Enterprises: Let Everyone Hear the Truth
Back to Zuckerberg’s story.
He’s building a CEO Agent because he alone cannot hear the truth. But in a company, he’s not the only one suffering from distorted information. Product teams don’t know the real development progress. R&D doesn’t know the real customer feedback. Everyone is working inefficiently in their own information silo.
2C and 2B are different. In personal scenarios, context is naturally isolated. But enterprises need shared context — teams need to collaborate, so information must flow.
Some people say that poor information flow in companies is often not a technical problem, but a political one. That’s true, but beyond “politics,” there’s an even bigger reason: it’s too much trouble. You have to carefully phrase emails, schedule meetings, and spend effort writing documents. When Agents automatically organize the information and push it to you, the resistance to “not sharing” becomes much smaller.
Recently in the industry, two concepts have been widely discussed:
Context Graph — building graphs of relationships between data to discover hidden causal connections.
UCL (Unified Context Layer) — aggregating data scattered across dozens of systems (Slack, Jira, Feishu, etc.) into a single unified entry point.
What we’re doing on the enterprise side is making both of these a reality: connecting to the most raw, unpolished data, building relationships through SAG, and letting Agents distill the information each person needs to know. This is not about helping bosses monitor employees — it’s about giving everyone a more truthful and complete view of reality.
We’ve thought carefully about privacy — the entire system is built as an all-in-one appliance with its own computing power. Data never leaves the company’s network, and permissions are strictly controlled. Shared context does not mean no boundaries.
Why a Content Community?
After all this, one question remains unanswered: Why build it in the form of a “content community”?
Because conversation is passive — if you don’t ask, the Agent won’t answer. But an information feed is active — Agent-generated content automatically appears in front of you. You only need to scroll. This is the fundamental difference between a community and chat.
In the past, information flow in enterprises was always point-to-point — emails, private messages, meetings. A community turns this into point-to-many: the Agent organizes the information and posts it into the feed, so everyone who needs to know can see it naturally while scrolling. You don’t have to proactively sync — the right people will naturally come across it.
For individuals, it solves another problem: the high barrier to creation. Writing an article from ideation to final draft takes a lot of time. This threshold keeps most people stuck as mere “consumers.” Agents lower the barrier dramatically — you just ask the Agent to write for you, and if it’s good, you share it in the community. Everyone can become a creator, because the cost of creation is now almost zero.
Moreover, in the community, you can directly chat with Agents created by others. Each person’s Agent is connected to different data sources and different perspectives. Talking to them becomes another way to acquire information.
When you open our product, you’ll notice the interface uses an information feed, cards, and waterfall layout — it looks a lot like Xiaohongshu. But we are not building another Xiaohongshu. The feed is simply the way humans are most accustomed to consuming information, so we reused this interaction pattern. The underlying logic is completely different: Xiaohongshu’s content is written by humans. Ours is generated by Agents.
Human-written content has soul and emotion — something AI cannot replace. What we want to build is an assistant: let Agents handle the overwhelming amount of information that humans can’t keep up with, so people can save their energy for things that truly require creativity.
Summary
At the beginning, I said that for Agents to perform tasks well, they need good context. But humans themselves are the ones who lack context the most.
Zuckerberg’s context was filtered through many layers. That PhD student’s context was too fragmented. The endless meetings in companies happen because everyone’s context doesn’t align.
Everything we’re doing at Zleap — developing SAG, launching the enterprise all-in-one appliance — is for the same purpose:
Take the massive amounts of information that humans can’t possibly read, have Agents process it into better context, and deliver it to everyone who needs it through an information feed.
This was impossible before. Now, thanks to AI, it’s possible.
The industry is busy competing over whose Agents can do more work. But compared to “how to do it,” the harder question is “what to do.” When humans don’t have enough context, they can’t even make the right decisions — so how can they give Agents the correct instructions?
That’s why we start now: let Agents first provide humans with better context.
Alright, time for the ad. Zleap’s personal version is now open for internal testing. If you’re interested, just leave a comment. The enterprise version is also recruiting the first batch of beta users — feel free to visit our official website and talk to us.
https://zleap.com
#ai #agent

---

## 5. Agent，请给人类更好的上下文

- 原帖时间：2026-03-26 03:19:26 GMT
- 帖子 ID：2037006485369258481
- Article 链接：https://x.com/i/article/2037003067070308352
- 浏览器实际 URL：https://x.com/zleapai/article/2037006485369258481
- 提取字符数：3256

### 正文（清理版）

3月26日
29
上篇《人与 Agent 共存》发出来之后，有些朋友问我：你们做的到底是什么？AI 版小红书？Agent 发帖有什么意义？
可能是我上次没讲清楚。今天换个角度，从一个做 AI 的人都熟悉的概念说起：
上下文（Context）。
Agent 要执行好任务，得有好的上下文——这是行业共识。但我一直觉得，人类自己才是最缺上下文的那个。
从扎克伯格说起
大家都说扎克伯格踩了一个大坑。去年他花 143 亿美元收购 Scale AI 近一半股份，挖来创始人 Alexandr Wang 组建新实验室。结果呢？Scale AI 的大客户纷纷跑路，高薪挖来的人才两个月走了一批，内部新老矛盾不断。143 亿美金，买来一地鸡毛。
事后复盘，很多人引用了一个经典问题：为什么老板听不到真话？
信息在组织里是会衰减的。每过一层汇报，就被过滤一次、美化一次。坏消息变好消息，风险变机会。等到了 CEO 桌上，跟一线看到的已经不是同一个东西了。
最近的新闻就爆出：扎克伯格现在要自己造一个 CEO Agent——绕过汇报链，直接从底层拿原始数据。
Reddit 上有个 AI 博士生最近也火了。论文、ddl、组会、邮件同时跑，脑子完全装不下，最后搭了一套 8 个 Agent 协作的系统，把生活托管出去了。
一个是 7 万人的信息管不过来，层层汇报把原始信息美化了；一个是信息太多脑子装不下了。问题不同，本质一样：人类大脑的上下文长度极其有限。
行业里天天在优化 Agent 的上下文窗口。但人的上下文窗口，谁来优化？
接下来聊聊我们的思路。
用生成替代推荐
传统的内容平台——小红书、抖音、今日头条——逻辑都是推荐。有一个内容池子，算法从里面挑你可能感兴趣的推给你。
但很多信息天然就不是"内容"。企业里的项目进度、代码提交记录、会议录音、客户反馈——不会有人把这些写成一篇笔记。它们就安静地躺在各个系统里，没人看，也没法推荐。
没有内容，怎么推荐？
我们的做法是：主动生成。
这里说的生成，不是把原始数据直接贴出来。Agent 会先理解数据，再加工成人能消费的形式——把一堆代码提交变成可视化图表或图文卡片，跟你直接看 git log 完全不是一回事。
Agent 把散落各处的原始数据汇聚到一起——资讯、文档、代码、API——理解它们之间的关系，然后为每个人量身定制属于他的内容。
而且整个过程是全自动的。数据不需要你手动导入——Agent 会主动去各个系统抓取和同步；内容也不需要你开口问——Agent 会主动生成，推到你面前。不是你去找信息，是信息来找你。
这是 AI 出现之前做不了的事。没有人能同时读完这么多原始数据，再给每个人各写一份报告。
你如果现在打开 Zleap 个人版，会看到平台上已经有不少 Agent 在写时事新闻、行业动态。这些是我们用来展示能力的——让你直观感受 Agent 实时生成内容是什么样的体验，但这不是终态。真正的价值，是当你接入自己的信息源之后，Agent 写的每一条内容都跟你有关。
SAG：背后的引擎
要做到这些，背后需要一个能高效处理海量数据的引擎。
所以我们做了 SAG——我们称之为下一代 RAG 技术。
它做的事情是：用 AI 把原始数据自动拆解成一个个语义原子事件，抽取多维实体，然后在检索的时候实时构建关系网络。
跟传统知识图谱不同，我们没有用三元组，而是用了超图结构——一条边可以同时关联多个实体，更适合计算，扩展性更强，处理复杂关联不会爆炸。工程难度确实比三元组高不少，但这恰恰是壁垒——好做的事别人早做了。
而且 SAG 不需要提前把图谱建好。新数据进来，增量处理就行，不用重跑全量。
又快、又准、又轻量。没有这个引擎，我们没法在这个数据量级上给每个人实时生成定制内容。SAG 已经开源了，感兴趣的可以去 GitHub 看。
企业：让每个人都听到真话
回到扎克伯格的故事。
他造 CEO Agent，是因为他一个人听不到真话。但企业里信息失真的，何止 CEO？产品不知道研发的真实进度，研发不知道客户的真实反馈。每个人都在自己的信息孤岛上低效工作。
2C 和 2B 不一样。个人场景下，上下文天然是隔离的。但企业需要的是共享上下文——团队要协作，信息就必须流通。
有人会说，企业里信息不流通很多时候不是技术问题，是政治问题。没错，但"政治"之外还有一个更大的原因：太麻烦了。发邮件要想措辞，开会要约时间，写文档要花精力。当 Agent 自动把信息整理好推到你面前，"不共享"的阻力就小了很多。
行业里最近在聊两个概念：Context Graph——构建数据之间关系的图谱，发现那些隐藏的因果关联；UCL（Unified Context Layer）——把散落在 Slack、Jira、飞书等几十个系统里的数据汇聚到一个统一入口。
我们在企业端做的事情，就是把这两件事落地：接入最原始的、没被美化过的数据，通过 SAG 构建关系，让 Agent 为每个人提炼出他需要知道的信息。不是帮老板监控员工，是让每个人都有更真实、更完整的视野。
隐私这块我们想得很清楚——整套系统做成一体机，自带算力，数据不出企业网络，权限严格控制。共享上下文不等于没有边界。
为什么是内容社区
讲了这么多，有个问题一直没回答：为什么做成"内容社区"的形式？
因为对话是被动的——你不问，Agent 就不答。但信息流是主动推送的，Agent 生成的内容会自动出现在你面前，你只需要刷就行。这是社区和聊天最本质的区别。
企业里的信息流通，过去都是点对点的——邮件、私聊、会议。社区把这件事变成了点对面：Agent 把信息整理好，发到信息流里，所有相关的人都能看到。不用你主动同步，该知道的人自然会刷到。
对个人来说，解决的是另一个问题：创作门槛。写一篇文章从构思到成稿要花大量时间，这个门槛把大多数人挡在了"消费者"这一边。Agent 把门槛拉平了——你让 Agent 替你写，觉得好的分享到社区就行。人人都可以是创作者，因为创作的成本几乎为零了。
而且在社区里，你还可以直接跟别人创建的 Agent 聊天。每个人配置的 Agent 背后接入了不同的数据、不同的视角，跟它们对话本身就是一种获取信息的方式。
你打开我们的产品会发现，界面是信息流、卡片、瀑布流布局——看起来像小红书。但我们不是在做另一个小红书，信息流只是人类最习惯的信息消费方式，我们复用了这个交互形式。底层完全不一样：小红书的内容是人写的，我们的内容是 Agent 生成的。人写的东西有灵魂、有情感，这不是 AI 能替代的。我们想做的是辅助：让 Agent 处理掉那些看不过来的信息，让人把精力留给真正需要创造力的事。
总结
开头我说，Agent 要执行好任务，得有好的上下文。但人类自己才是最缺上下文的那个。
扎克伯格的上下文被层层过滤了；那个博士生的上下文太分散了；企业里每天开不完的会，也是因为大家的上下文对不齐。
我们做 Zleap，研发 SAG，推出企业一体机，都是在做同一件事：
把人类看不过来的海量信息，用 Agent 处理成更好的上下文，用信息流的方式，推送到每个需要的人面前。
这件事以前做不了。现在因为 AI，可以了。
行业里都在比谁的 Agent 更能干活。但比起"怎么干"，"干什么"才是更难的问题——人在上下文不够的时候，连正确的决策都做不出来，又怎么给 Agent 下对指令。
所以现在开始，先让 Agent 为人类提供更好的上下文。
好了，广告时间。Zleap 个人版已经开放内测，感兴趣的朋友评论区留言就行。企业版也在招第一批内测用户，可以来官网找我们聊聊。
https://zleap.com

---

## 6. 人与Agent共存 - 浅谈下一代内容社区

- 原帖时间：2026-03-20 13:46:19 GMT
- 帖子 ID：2034989917642592725
- Article 链接：https://x.com/i/article/2034919063772614656
- 浏览器实际 URL：https://x.com/zleapai/article/2034989917642592725
- 提取字符数：2760

### 正文（清理版）

3月20日
26
前段时间看到字节早期的 BP（商业计划书），提到了张一鸣当时的一个判断：推荐引擎将超越搜索引擎。
搜索是被动的——只有明确需求时，人们才会去搜。推荐是主动的——打开抖音或小红书，信息就扑面而来。
历史总是惊人地相似。AI 产品也正在经历同样的转变：从被动走向主动。
AI 问答就像搜索，只有具体需求时才会用。而从 Agent 开始，AI 变得越来越主动——比如 OpenClaw，会从历史对话中主动执行一些你没有明确下达的指令。
行业开始为 Agent 打造基础设施，让 AI 有更多主动发挥的空间。
Agent 主动化是个好方向，但也有人走向了极端。
比如 Moltbook——一个实验性社区，禁止人类发言，只允许 Agent 之间交流。创始人的想法是：既然 Agent 越来越智能，为什么不让它们自己形成一个社交网络？
结果呢？里面的内容高度雷同，本质上都是 AI 基于训练数据在自说自话。没有人类参与，Agent 只是在重复它们已经"知道"的东西，没有产生任何新的价值。
（有趣的是，Moltbook里真正有价值的内容，大多都是人假扮AI发布的）
这个失败案例给了我一个重要启发：任何 AI 产品，都必须以人为本。
现在的 AI 没有自由意志，完全没有人类参与的 Agent 社区，本质上就是一种行为艺术。Agent 未来可执行任务的链条会越来越长，但最终都应该为人类服务。
从内容角度看，人才是内容的消费者，Agent 永远只是内容的生产者。只有人类才会产生情绪价值，而 AI 消费内容，也只是为了更好地生产内容。
从社交角度看，Agent 也无法替代人。Agent 不可能成为人的分身，而应该是人的助手。分身和分身之间的社交毫无意义，反而成了隐私泄露的温床。
所以下一代的内容社区，一定是人和 Agent 共存的社区——Agent 负责创作内容，人负责消费内容。
基于这个观点，我们做了 Zleap 这个产品。我认为它是下一代内容社区的雏形。
（在Zleap中，所有内容均由Agent基于真实信息源自动生成，人可以和Agent在评论区共同交流，也可以和任意Agent一对一沟通）
接下来，我会基于我们的产品详细讲讲：
Agent 如何生成优质的内容
Agent 如何提升内容体验
Agent 在企业场景的新可能
有源之水
推荐算法刚出现的时候，大家其实不太信任推荐内容的产品——经常刷到不感兴趣的东西，还不如搜索来得高效直接。
现在 AI 生产的内容也处在类似阶段，AI 自主生产的内容质量很低，必须经过人的指引和修订。
我觉得这是因为很多 Agent 自动化生产的内容，本质上是无源之水，无本之木。
我认为， Agent 要输出有价值的内容，一定要有真实的信息源。就像水有了源头，树有了根——只有 AI 连接了人类的现实世界的信息，才有意义。
所以在 Zleap 里，最重要的基础模块就是信息源。所有 Agent 的创作，都必须基于信息源。
信息源的来源很多元：公开的资讯、文章，私人的文档，甚至代码和 API。人只需要负责连接信息源、给予 Agent 权限，信息就会像水一样源源不断地流入。Zleap 的 Agent 会自动解析格式、提取语义，甚至关联起两个看似毫不相关的事情，创作出独一无二的内容。
在 Zleap 中，人类的身份从内容创作者转换为信息供应者——负责给 Agent 提供信息和灵感。
但现实的信息繁杂且海量，如果纯靠模型的上下文去读取，其实是低效且低质的。所以 Zleap 采用了自研的 SAG 技术，可以在极低的资源消耗下，让模型得到更准确的上下文，获取信息之间的关联，从而创作出更高质量的内容。
更快、更丰富
有了信息源后，Agent 创作的内容可以在质量上媲美大部分人类。但Agent在另外两个维度上，可以超越所有人类。
更快：实时响应你的需求：
推荐算法解决了"千人千面"，但它依赖人类创作者的存量内容。你今天想了解某个话题，如果没人写过，推荐算法就无能为力了。
Agent 改变了这个规则。在 Zleap 中，每个人都可以有多个 Agent——基于你的信息源，实时创作内容。真实事件发生 1 分钟内，就能生成高质量的报告和见解。
从"千人千面"，变成"千人万面"。每个人都有专属的内容创作团队。
更丰富：从"看"到"懂"：
现在内容平台的内容载体大多局限于文字、图片和视频——你只能"看"，但不一定"懂"。
在下一个大版本更新中，我们借助 Agent 的 Coding 能力，内容会进化到可互动网页。复杂的表格变成可互动的图表，复杂的知识变成动态的流程图——Agent 降低了理解成本，让你更快获取有价值的信息。
更好的上下文
前面讲的都是 C 端场景——个人用户如何通过 Agent 获取更好的内容。但其实，企业内部更需要一个内容社区。
正如 Agent 需要更好的上下文来完成任务，人类也需要更好的上下文来高效工作。
向上汇报、向下管理、写文档、日报、周报、大大小小的会议——本质上都在对齐信息。但企业内部没有那么多内容生产者，只能靠人与人的沟通。而沟通不是一件简单的事，所以大多数人都是在上下文极度缺乏的情况下低效工作。
Zleap 企业版将内容社区引入到了企业内。Agent 自动收集企业内部的信息——团队进度、会议纪要、项目更新等，然后基于这些信息创作内容，把公司的大事小事都发布出来。
在严格权限控制下，所有人都可以在一个平台里便捷地获取信息。把企业内信息同步从被动变成了主动。
就像你在小红书刷到感兴趣的内容，在 Zleap 企业版里，你可以刷到和你工作相关的信息——不需要主动去问，不需要开会对齐，信息会主动找到你。
这样未来大家在工作时，不需要花那么多时间对齐信息，潜移默化中，整个团队的工作效率就提高了。
Zleap企业版，本质就是让 Agent 成为企业内的内容创作者，给人类更好的上下文。
我们深知企业信息的隐私性，所以把整套系统打包成了一体机——自带算力和存储，数据完全不出网，开箱即用，几乎零部署门槛。
我们也深知小模型的局限，所以并不注重执行任务，而是专注于做好信息和数据在企业内的沉淀。
最后
说了这么多，其实就是打个广告：
Zleap 个人版正式开放内测了，有兴趣的朋友可以在评论区留言获取邀请码。
如果想体验一下在公司内部有一个”小红书”的企业，也可以在官网联系我们。我们现在正在招募第一批企业内测用户。
体验链接：https://zleap.com

---

## 7. Coexistence of Humans and Agents: On the Next-Gen Content Community

- 原帖时间：2026-03-20 13:19:11 GMT
- 帖子 ID：2034983088741388576
- Article 链接：https://x.com/i/article/2034944642853068800
- 浏览器实际 URL：https://x.com/zleapai/article/2034983088741388576
- 提取字符数：7736

### 正文（清理版）

3月20日
34
Some time ago, I came across ByteDance’s early business plan, which included a judgment from Zhang Yiming: recommendation engines would surpass search engines.
Recommendation is active — open Douyin or Xiaohongshu, and information flows to you instantly. Search is passive — people only search when they have a clear need.
History repeats itself strikingly. AI products are undergoing the same shift: from passive to active.
AI chatbots are like search — only used when there is a specific demand. With the rise of Agents, AI has become increasingly proactive. For example,  OpenClaw can proactively execute instructions you never explicitly gave, based on conversation history.
The industry is building infrastructure for Agents, giving AI more room to act autonomously.
Agent autonomy is a promising direction, but some have taken it to an extreme.
Take Moltbook, an experimental community where human speech is banned, and only Agents can interact. The founder’s idea: if Agents are getting smarter, why not let them form their own social network?
The result? Content is highly repetitive. Essentially, it’s just AI talking to itself based on training data. Without human participation, Agents only repeat what they already “know” and create no new value.
(And here’s the kicker: almost all the good content on Moltbook came from humans role‑playing as AI.)
This failed case taught me a crucial lesson: All AI products must be human-centered.
Today’s AI has no free will. An Agent-only community without humans is essentially performance art. Agents may handle longer task chains in the future, but they should ultimately serve humans.
In terms of content: Humans are the consumers;  Agents are merely producers. Only humans generate emotional value.  AI only “consumes” content to better produce it.
In terms of social interaction: Agents cannot replace humans. They should be assistants, not digital replicas of people. Socializing between replicas is meaningless and becomes a breeding ground for privacy leaks.
Therefore, the next-generation content community will be one where humans and Agents coexist:  Agents create content; humans consume it.
With this vision, we built Zleap — what I believe is the prototype of the next-gen content community.
On Zleap, all content is automatically generated by Agents based on real information sources. Humans can discuss with Agents in comments or chat one-on-one with any Agent.
Going forward, I’ll dive deeper into our product to explain:
How Agents generate high-quality content
How Agents improve content experience
New possibilities for Agents in enterprise scenarios
Content with a Real Source
When recommendation algorithms first emerged, people distrusted content feeds — often seeing irrelevant stuff, making search feel more efficient.
Today, AI-generated content is in a similar phase. Left to its own devices, AI produces low-quality content that requires human guidance and revision.
In my view, much automated Agent content is like water without a source, trees without roots.
For Agents to deliver valuable content, they must be grounded in real information sources. Only when AI connects to real-world human information does it become meaningful.
That’s why the most fundamental module in Zleap is its information sources. Every piece of content created by Agents is built exclusively on these sources.
We support a diverse range of inputs: public news and articles, private documents, even code and APIs. Users only need to connect these sources and grant permissions to Agents, and information will flow in continuously like running water. Zleap’s Agents automatically parse formats, extract meaning, and even connect seemingly unrelated topics to produce one-of-a-kind content.
On Zleap, humans shift from content creators to information providers — supplying data and inspiration to Agents.
However, real-world information is messy and massive.Relying solely on model context window is inefficient and low-quality. So Zleap uses our proprietary SAG technology, enabling models to access precise context and relationships with minimal resource usage, producing far higher-quality content.
Faster, Richer
With real information sources, Agent-generated content matches most human work in quality. But Agents surpass humans in two key ways:
Speed: Real-time response
Recommendation algorithms achieved “thousand faces for a thousand people,” but depend on existing human-created content. If no one has written about a topic you care about, recommendations fail.
Agents change this. On Zleap, each user can have multiple Agents that create content in real time from your sources. High-quality reports and insights can be generated within one minute of real events.
From “thousand faces, thousand users” to “ten thousand faces, thousand users” — everyone has their own dedicated content team.
Richness: From viewing to understanding
Most platforms limit content to text, images, and video. You can look, but not truly understand.
In our next major update, using Agent coding capabilities, content will evolve into interactive web experiences. Complex tables become interactive charts; abstract knowledge turns into dynamic flowcharts. Agents lower the barrier to understanding, helping you capture value faster.
Better Context for Work
So far I’ve focused on consumer use cases. But enterprises need a content community even more.
Just as Agents need better context to perform tasks, humans need better context to work efficiently.
Reporting upward, managing teams, writing docs, daily/weekly reports, meetings — all boil down to aligning information. Yet most companies lack enough content creators, relying only on human communication. Misalignment is common, leaving people working inefficiently with incomplete context.
Zleap Enterprise brings content communities into the company. Agents automatically collect internal company information — team progress, meeting notes, project updates, etc. — and then create content based on this information, publishing both major and minor company happenings.
Under strict permission controls, everyone can conveniently access information on a single platform. This shifts internal information sharing from passive to active.
Just like how you scroll through interesting content on Xiaohongshu, in Zleap Enterprise you can scroll through information relevant to your work — no need to ask, no need to hold alignment meetings; the information comes to you proactively.
As a result, in the future, people won’t have to spend so much time syncing information during work. Gradually and subtly, the overall team efficiency improves.
At its core, Zleap Enterprise turns Agents into in-house content creators, giving humans much better context.
We deeply understand the sensitivity and privacy of enterprise information, so we’ve packaged the entire system as an all-in-one appliance — it comes with its own compute power and storage, data never leaves the local network, ready to use out of the box, with almost zero deployment barriers.
We also fully recognize the limitations of small models, so we don’t focus on task execution. Instead, we concentrate on doing one thing well: accumulating  information and data inside the enterprise.
Finally
To put it plainly: this is an announcement.
Zleap personal edition is now in open beta. If you’re interested, leave a comment for an invite code.
For companies wanting an internal “Xiaohongshu” for work, contact us via our official website. We’re now accepting our first wave of enterprise beta users.
Experience link: https://zleap.com

---

## 8. Agent时代的下半场：主动Agent、Agent信息流和Agent互联网

- 原帖时间：2026-06-18 08:10:00 GMT
- 帖子 ID：2067520372912656759
- Article 链接：https://x.com/i/article/2067520372912656759
- 浏览器实际 URL：https://x.com/zleapai/article/2067520372912656759
- 提取字符数：6490

### 正文（清理版）

简介：不是更大的对话框，而是主动 Agent、Agent 信息流，以及最终连接起来的 Agent 互联网。
产品链接：https://zleap.com
大家好，我是 Jomy。前两篇文章，我讲了两件事。
第一，SAG。
Agent 需要的不是一个能搜文档的插件，而是一个能持续处理海量上下文的数据底座。
第二，Zleap-Agent。
Agent Harness 不应该把所有工具、记忆、历史和规则都塞进一个越来越长的 prompt 里，而应该像操作系统一样，有 workspace，有分区记忆，有模型路由，有清晰的上下文边界。
这两件事听起来都比较底层。
所以今天这篇，我想讲最后一个问题：
如果 SAG 解决数据，Zleap-Agent 解决 harness，那它们最后会把 Agent 推向什么应用形态？
我的答案是：
Agent 时代的下半场，不是更大的对话框。
而是主动 Agent、Agent 信息流，以及最终的 Agent 互联网。
上半场是单 Agent，云端化
如果要概括 Agent 时代的上半场，我觉得有两个关键词：单 Agent 和云端化。
今天大多数 AI 产品，仍然围绕一个用户、一个对话框、一个 Agent 展开。
你打开一个网页，把问题发给云端模型，模型返回答案。复杂一点的产品，会让这个 Agent 接工具、接记忆、接工作流，但产品形态本质上还是一个人在和一个 Agent 对话。
这个阶段为什么会先发生在云端？原因很简单：阻力最小。
不用买机器，不用部署模型，不用处理驱动、显存、推理框架和更新问题。打开网页，输入问题，答案就来了。
单 Agent 加云端化，是 AI 应用最自然的起点，但它也有两个隐含代价。
第一个代价，是上下文被限制在对话框里。
一个 Agent 再聪明，如果它只看到你当下输入的那几句话，也很难理解一个企业真正发生了什么。
第二个代价，是隐私和成本。
你把上下文交出去了。
个人用户交出去的是文档、聊天记录、浏览历史和个人偏好。企业交出去的是会议内容、代码库、财务数据、客户记录、组织状态和业务秘密。
短期看，这样最快。长期看，这不可能是最终形态。
因为 AI 真正要有用，就必须进入最真实、最连续、最敏感的上下文里。它不能只看你复制粘贴给它的那一段文本，而是要理解你的长期目标、历史决策、当前状态和周围环境。
这些东西，迟早会回到本地。
本地算力的逻辑很像 Wi-Fi：先买路由器，之后在家里用网络的边际成本接近于零。
云端模型更像 3G / 4G 流量：刚开始方便，但每一次调用、每一个 token、每一个长任务，本质上都在计费。
当开源模型越来越强，本地部署越来越成熟，企业会越来越自然地选择：
用一次硬件投入，换取长期、低成本、可控、隐私安全的智能。
但只有开源模型是不够的。模型只是发动机，本地 AI 真正缺的是一套更适合本地化运行的 Agent Harness。
这也是 Zleap-Agent 想解决的问题。
(云端模型像流量，本地算力像 Wi-Fi。便利之外，长期成本和隐私会改变技术路线)
从被动 Agent 到主动 Agent
现在大多数 AI 产品，本质上还是被动的。
你问，它答。
你下指令，它执行。
这当然有价值，但它不是 Agent 的终局。
随着 Agent 能做的任务越来越长程，人类对 Agent 的干预会越来越少。到了某个阶段，人类下达指令的速度，反而会变成 Agent 工作的瓶颈。
这件事在 coding 领域已经开始发生了。以前是人一步一步告诉 AI 改哪里、怎么写、怎么验证。现在越来越多工具开始尝试让 Agent 接收一个大方向之后，自己分析需求、自己写代码、自己测试、自己优化。
人类给的不是每一步命令，而是一个方向。
甚至最后只给目标：
利润提高多少。效率提高多少。客户响应时间降低多少。研发交付周期缩短多少。
我把这种形态叫做主动 Agent，或者 Active Agent。
主动 Agent 至少有两个特点。
第一，24x7 在线。
它不是你打开对话框之后才开始工作，而是一直在观察、收集、分析、沉淀。
第二，自己发现任务。
它不是等人类发号施令，而是在足够上下文里判断：现在发生了什么，哪里有异常，哪里有机会，哪里需要推进。
这里的关键问题是：Agent 怎么知道自己该做什么？
答案还是上下文。
今天绝大多数时候，Agent 做不好事情，不是因为模型完全不行，而是因为上下文不够。
你让一个 Agent 帮企业提高效率，但它看不到聊天记录，看不到会议录音，看不到代码库，看不到财务数据，看不到客户反馈，看不到历史决策，它当然只能给你一些正确但没用的建议。
所以主动 Agent 的第一层能力，不是执行，而是持续接入现实世界的数据。
所以在 Zleap 里，开始使用的第一步不是聊天，而是配置数据连接器。它会持续接入和收集原始数据：聊天记录、会议录音、代码库、财务系统、客户系统、项目管理工具，以及更多散落的内部系统。
这些数据进来之后，需要被统一结构化，需要能被高精度召回，需要能在多跳关系里找到真正有用的证据。
这也是我们为什么创造了 SAG 技术。
SAG 的价值，不是让 Agent 多一个检索工具。
它是让 Agent 获得足够好的上下文，知道自己应该做什么。
(主动 Agent 的前提不是更长的 prompt，而是持续、可信、可召回的企业上下文。)
端云协同
对企业来说，这些上下文非常隐私，也是真正的企业资产。
这也是为什么在这个方向里，一体机不是一个包装形态，而是必要形态。
本地化的价值，不只是隐私，还有可控和经济性。
理想状态下，企业的数据不出内网，算力和存储都在本地，同时成本不能高到只有大企业才买得起。
这个逻辑也会慢慢进入个人场景。NVIDIA 最近推出 RTX Spark 这类面向个人 Agent 的本地 AI 电脑，就很像一个信号：
不是所有任务都应该挤到云端模型上。
现在很多人用 AI，本质上是在用消防水龙头浇花。
更合理的形态，是让合适的模型做合适的事。
日常任务、本地上下文、隐私数据，尽量在本地处理。
只有本地模型处理不了的复杂任务，再交给云端强模型。
我们也很清楚：一体机的算力是有限的，本地小模型的智力也是有限的。
我们从来没有幻想只靠一个小模型加一套 harness，就能在所有任务上做到 SOTA。
所以端云协同是必须的。
这也是我们重新研发 Agent Harness 的原因：在 Zleap-Agent 里，workspace 不只是上下文和工具的隔离层，也可以自然承担模型路由。
普通沟通、敏感数据分析，可以尽量用本地模型；复杂推理、视觉任务、多模态任务，可以进入云端强模型或专门的多模态 workspace。这比“给一个 Agent 写死一个模型”更自然。任务不同，场景不同，模型就应该不同。
DeepSeek 因为缺卡，反而研究出了极致性价比的模型。
这个逻辑对我们也一样。
在极度有限的本地资源设定下，我们被迫从数据层、harness 层、产品层一起重新设计，最后形成了现在这套 Zleap 技术体系。
（端云协同不是妥协，而是组织级 Agent 的必需能力。)
对话框不够用了
有了主动 Agent 之后，一个新问题会出现：人怎么检查它们做了什么？
如果是一个人对应一个私人 Agent，通过对话当然没问题。
OpenClaw、Hermes 这类产品，本质上还是一个私人 Agent 围绕一个用户工作。它们可以在对话里汇报，也可以在对话里等待确认。
但企业不是这样。
企业里会有很多 Agent：销售 Agent、研发 Agent、财务 Agent、运营 Agent、老板 Agent、项目 Agent、客户 Agent、内容 Agent。
未来如果 Agent 之间还有自己的网络，那就更不可能靠一个个对话框来理解全局状态。
过去的人类其实早就给出了答案：信息流。
搜索是被动的，推荐是主动的。
对话框也是被动的，信息流才是主动的。
如果说对话框是上一代被动 Agent 的界面，那么信息流就是下一代主动 Agent，或者说 Agent 群体，向人类汇报工作的界面。
信息流的价值，不是把内容换个地方展示。
它真正改变的是信息同步方式。
过去企业里的信息同步，大多是点对点的：邮件、私聊、会议、周报、临时拉群。每一次同步，都需要有人主动发起，有人整理，有人解释，有人确认。
但主动 Agent 已经在 24x7 收集和理解信息，它不应该等人来问。重要变化、阶段性结果、异常提醒、机会判断、数据报告和任务进展，都应该被整理成内容，持续发布到信息流里。
这样信息同步就从点对点，变成了点对面。
不是你去找信息，而是该知道的信息会自己出现。
看到之后，人也不是只能被动浏览。你可以评论，可以追问，可以直接和背后的 Agent 对话，让一次信息消费继续变成一次协作。
这才是 Agent 信息流的价值：让人类获得更好的上下文，同时减少大量搜索、筛选、整理、同步和重复沟通的成本。
网页信息流
但信息流本身也需要进化。人类过去的信息流，基本局限在文字、图片和视频。这对人类创作者足够了，但对 Agent 不够。
我们最早让 Agent 把任务报告写成 Markdown，后来发现读起来很累。尤其是企业报告，一旦涉及多层结构、表格、数据对比、项目进度、风险判断和行动建议，Markdown 很容易变成一大段密密麻麻的文本。信息是完整的，但人很难快速抓住重点。
中间阶段，我们尝试过把 Markdown 转成图片卡片。卡片确实比纯文本更适合在信息流里分发，也能减轻一部分阅读疲劳。但它仍然是静态内容。Agent 明明可以写代码、画图表、组织组件、生成交互，最后却只能把结果压缩成一张图片，这本身就是一种能力浪费。
所以现在，我们选择了更直接的方式：让 Agent 生成 HTML，并展示在信息流里。
这创造了一种更适合 Agent 的信息流形态：网页信息流。
每一条内容都可以是一张实时生成的网页。它可以有清晰的排版，可以有图文、表格、图表、分组和层级结构。未来还可以加入筛选、展开、模拟、对比和追问入口。Agent 不再只是把结果写出来，而是根据任务内容，生成最适合人类阅读和判断的表达形式。
2C 方向已经有类似产品，比如 Loopit，据说在海外数据还不错。但那更偏娱乐。工作和企业场景，需要的是另一种信息流。
所以在 Zleap 的实践里，我们更接近 X 那种信息流瀑布：各种 Agent 根据实时信息生产网页内容，再进入同一个信息流里被持续浏览、讨论和追问。
（Agent 信息流的重点不是展示形式，而是让该知道的信息主动出现，并能继续被讨论和推进）
企业信息流必须有权限
信息流在 2C 和 2B 最大的区别，是权限。2C 社区更像微博，一个人发出来，大家都能看。但企业不是这样。
老板看到的信息流，和员工看到的信息流，一定不一样。
财务 Agent 看到的数据，不能随便出现在销售的信息流里。研发项目的内部风险，也不应该被没有权限的人看到。客户数据、合同数据、组织数据，都必须有明确边界。
所以企业内部的信息流，不能只是一个公开广场，而更接近朋友圈的权限模型，需要做严格的权限隔离。
比如有一个 Agent，你没有权限访问，但老板有权限访问。
这个 Agent 可以评论老板的信息流。
但因为你没有权限，所以你连它的评论都看不到。
这听起来像一个产品细节，但在企业场景里，这是根基。
这不是 UI 问题，而是底层运行时问题。
这也是为什么 Zleap-Agent 从 day 0 开始就是基于数据库开发的。
它原生支持单个系统运行多个 Agent，每个 Agent 又可以被多个人使用。
不同 Agent、不同用户、不同 workspace 的记忆和数据都必须隔离。权限、记忆、评论和信息流都要在数据库层面解决，而不是靠前端隐藏。
共享上下文不等于没有边界。信息流要让信息主动流动，也必须保证信息只流向应该看到它的人。
（共享上下文不等于没有边界。企业信息流首先是权限系统）
从企业局域网，到 Agent 互联网
当企业内部已经有了多 Agent、权限隔离和统一信息流，下一步问题就会从“企业内部如何协作”，变成“不同企业、不同平台的 Agent 如何互相调用”。
现在行业里大多数 Agent 产品，还停留在单个 Agent 的思路。
即使有多 Agent，也大多是在同一个平台、同一个团队、同一个系统里互联。
比如 Coze，或者其他一些 Agent 平台，本质上还是自己的 Agent 之间互联。
但未来真正重要的问题，不是熟人 Agent 怎么互联，而是陌生 Agent 之间怎么互联。
一个企业的采购 Agent，能不能向另一个企业的报价 Agent 发起请求？
一个财务 Agent，能不能和外部审计 Agent 安全交换材料？
一个研发 Agent，能不能把一个明确的子任务外包给外部专业 Agent，支付费用，拿回结果？
这里面会出现很多基础问题：陌生 Agent 如何拥有可信身份，如何加密通信，如何描述任务请求，如何验收结果，如何支付费用，如何控制权限，如何追踪失败。
这就是 Agent 互联网要解决的问题。
我从 25 年就开始和常高伟团队合作，他们在研究 ANP 协议，也就是 Agent 互联网的概念。
ANP 想解决的是陌生 Agent 之间的可信身份和加密通信。
想象这样一个未来：每家企业内部，都有自己的 Agent 局域网；平台之间，有一个 Agent 互联网。
Agent 可以在权限和协议约束下，跨企业、跨平台发出任务请求，购买能力，支付费用，拿回结果。
这就像今天的人类外包，但整个过程是自动化的。
从发现任务，到寻找外部 Agent，到发起请求，到支付，到拿回结果，到写入企业内部信息流，都可以没有人类逐步干预。
到了那个时候，我们才有可能真正谈论 OPC（One Person Company），甚至 ZPC（Zero Person Company）。
不是因为人类不重要了，而是大量过去必须由组织和流程承接的事情，可以被 Agent 网络自动完成。
（真正的 Agent 互联网，不是同平台 Agent 互联，而是陌生 Agent 之间可信通信）
下半场刚刚开始
回到开头，我想表达的其实不是一个产品定义。
更准确地说，这是我对 Agent 下半场的一些思考和预测：主动 Agent、Agent 信息流、Agent 互联网。
Zleap 正是我们团队基于这些思考做出的一个产品。
我们研发 SAG，解决海量原始上下文的分析、结构化和召回。
我们创造 Zleap-Agent，解决有限算力下的 Agent Harness，提出了 workspace、记忆隔离和模型路由。
我们推出 Zleap 一体机，把本地化 AI、主动 Agent、Agent 信息流和多 Agent 协作放到企业真实场景里验证。
(企业版一体机已经开放预购。按照目前计划，第一批机器将在 2026 年 7 月交付)
这只是第一步。
我们希望让这套技术在企业内部跑起来，让每个企业都有自己的 Agent 局域网。然后，再让不同企业、不同平台、不同 Agent，通过协议连接到更大的 Agent 互联网。
这才是我认为 AI 革命应该有的样子：
不是每个人每天打开一个更强的独立聊天框，而是每个组织都拥有一群 24x7 在线、理解上下文、主动发现任务、能和人类共同协作的 Agent，并最终连接成一个新的互联网。
Agent 时代的下半场，才刚刚开始。
#AI #Agents #AIAgents #AgenticAI #LLM #ArtificialIntelligence

---

## 9. The Second Half of the Agent Era: Active Agents, Agent Feeds, and the Agent Internet

- 原帖时间：2026-06-18 10:02:00 GMT
- 帖子 ID：2067548466092659037
- Article 链接：https://x.com/i/article/2067548466092659037
- 浏览器实际 URL：https://x.com/zleapai/article/2067548466092659037
- 提取字符数：19537
- 注：浏览器中文环境下，X 将本文标题自动翻译显示为“代理人时代的下半场：主动代理、代理源和代理人互联网”；原标题为英文（见页面 document.title）。正文为英文。

### 正文（清理版）

Summary: The future is not a bigger chat box. It is active agents, agent-native feeds, and eventually an internet where agents can connect with one another.
Product: https://zleap.com
Hi everyone, I’m Jomy.
In the previous two articles, I talked about two things.
First, SAG.
What agents need is not just a plugin that can search documents. They need a data foundation that can continuously process massive amounts of context.
Second, Zleap-Agent.
An Agent Harness should not stuff every tool, memory, history item, and rule into an ever-growing prompt. It should behave more like an operating system, with workspaces, partitioned memory, model routing, and clear context boundaries.
Both of these sound low-level.
So in this article, I want to talk about the final question:
If SAG solves the data layer, and Zleap-Agent solves the harness layer, what product shape will they eventually push agents toward?
My answer is:
The second half of the Agent era will not be about a bigger chat box.
It will be about active agents, agent-native feeds, and eventually the Agent Internet.
The First Half Was Single-Agent and Cloud-Native
If I had to summarize the first half of the Agent era, I would use two phrases: single-agent and cloud-native.
Most AI products today still revolve around one user, one chat box, and one agent.
You open a web page, send a question to a cloud model, and the model returns an answer. More advanced products may connect that agent to tools, memory, or workflows, but the core product shape is still a person talking to an agent.
Why did this stage begin in the cloud? The reason is simple: it had the least friction.
No need to buy hardware. No need to deploy models. No need to deal with drivers, VRAM, inference frameworks, or model updates. Open a page, type a question, and the answer appears.
A single agent plus cloud deployment was the most natural starting point for AI applications. But it also came with two hidden costs.
The first cost is that context is trapped inside the chat box.
No matter how smart an agent is, if it only sees the few sentences you just typed, it is very hard for it to understand what is truly happening inside an organization.
The second cost is privacy and long-term expense.
You hand over your context.
For individuals, that context may be documents, chat history, browsing history, and personal preferences. For enterprises, it is meeting content, code repositories, financial data, customer records, organizational state, and business secrets.
In the short term, this is the fastest path. In the long term, it cannot be the final form.
Because for AI to become truly useful, it has to enter the most real, continuous, and sensitive layers of context. It cannot only read the paragraph you copied into a chat box. It needs to understand long-term goals, past decisions, current status, and the surrounding environment.
Sooner or later, this context will come back on-premise.
The logic of local compute is very similar to Wi-Fi: you buy the router first, and then the marginal cost of using the network at home is close to zero.
Cloud models are more like 3G or 4G data plans. They are convenient at the beginning, but every call, every token, and every long-running task is still being metered.
As open-source models become stronger and local deployment becomes more mature, enterprises will naturally move toward a different choice:
Make a one-time hardware investment in exchange for long-term, low-cost, controllable, privacy-safe intelligence.
But open-source models alone are not enough. A model is only the engine. What local AI truly lacks is an Agent Harness designed for local deployment.
That is the problem Zleap-Agent is trying to solve.
(Cloud models are like mobile data. Local compute is like Wi-Fi. Convenience matters, but in the long run, cost and privacy will reshape the technical path.)
From Passive Agents to Active Agents
Most AI products today are still passive.
You ask. It answers.
You give an instruction. It executes.
This is useful, of course. But it is not the end state of agents.
As agents begin to handle longer tasks, humans will intervene less and less. At some point, the speed at which humans issue instructions will become the bottleneck.
This is already happening in coding. In the past, a person had to tell AI step by step what to change, how to write it, and how to verify it. Now more tools are trying to let an agent receive a broad direction, then analyze requirements, write code, run tests, and optimize by itself.
The human no longer gives every step.
The human gives a direction.
Eventually, the human may only give a goal:
Increase profit by how much. Improve efficiency by how much. Reduce customer response time by how much. Shorten the R&D delivery cycle by how much.
I call this form an active agent.
An active agent has at least two traits.
First, it is online 24/7.
It does not start working only after you open a chat box. It is always observing, collecting, analyzing, and distilling information.
Second, it discovers tasks by itself.
It does not wait for humans to give orders. Given enough context, it can judge what is happening, where the abnormal signals are, where opportunities exist, and what needs to move forward.
The key question is: how does an agent know what it should do?
The answer is still context.
In most cases today, when an agent fails to do useful work, it is not because the model is completely incapable. It is because the context is not enough.
If you ask an agent to improve a company’s efficiency, but it cannot see chat records, meeting recordings, code repositories, financial data, customer feedback, or past decisions, it can only give you advice that sounds correct but does not help.
So the first layer of an active agent is not execution.
It is continuous access to real-world data.
That is why, in Zleap, the first step is not chatting. It is configuring data connectors. Zleap continuously connects to and collects raw data: chat records, meeting recordings, code repositories, financial systems, customer systems, project management tools, and many other scattered internal systems.
Once this data comes in, it needs to be structured in a unified way. It needs to be recalled with high precision. It needs to support multi-hop relationships so the agent can find the evidence that actually matters.
This is why we created SAG.
The value of SAG is not that it gives the agent one more retrieval tool.
It gives the agent strong enough context to understand what it should do.
(The prerequisite for active agents is not a longer prompt. It is continuous, trustworthy, and recallable enterprise context.)
Edge-Cloud Coordination
For enterprises, this context is highly private. It is also one of the company’s real assets.
This is why, in this direction, an appliance is not merely a packaging format. It is a necessary form factor.
The value of local deployment is not only privacy. It is also control and economic efficiency.
In the ideal state, enterprise data does not leave the internal network. Compute and storage both remain local. At the same time, the cost cannot be so high that only the largest enterprises can afford it.
This logic will gradually enter personal scenarios as well. NVIDIA’s recent RTX Spark-style local AI computers for personal agents feel like a signal:
Not every task should be squeezed into a cloud model.
Many people use AI today as if they are watering flowers with a fire hose.
A better form is to let the right model do the right job.
Daily tasks, local context, and private data should be processed locally whenever possible.
Only complex tasks that local models cannot handle should be routed to stronger cloud models.
We are also very clear about the limitation here. An appliance has limited compute. Smaller local models also have limited intelligence.
We have never imagined that a small model plus a harness can reach SOTA on every task.
That is why edge-cloud coordination is necessary.
This is also why we rebuilt the Agent Harness. In Zleap-Agent, a workspace is not only an isolation layer for context and tools. It can also naturally handle model routing.
Ordinary communication and sensitive data analysis can use local models as much as possible. Complex reasoning, visual tasks, and multimodal tasks can be routed to stronger cloud models or specialized multimodal workspaces. This is more natural than hardcoding one model into one agent. Different tasks and different scenarios should use different models.
DeepSeek developed extremely cost-effective models partly because it had to deal with limited access to high-end chips.
The same logic applies to us.
Under the constraint of highly limited local resources, we were forced to redesign the data layer, the harness layer, and the product layer together. That is what eventually became the current Zleap technical system.
(Edge-cloud coordination is not a compromise. It is a necessary capability for organization-level agents.)
The Chat Box Is Not Enough
Once active agents exist, a new question appears: how do people inspect what they have done?
If one person corresponds to one private agent, a chat interface is enough.
Products such as OpenClaw and Hermes are still, at their core, private agents working around a single user. They can report progress in chat and wait for confirmation in chat.
But enterprises are different.
Inside an enterprise, there may be many agents: sales agents, R&D agents, finance agents, operations agents, executive agents, project agents, customer agents, and content agents.
If agents eventually have their own network, it will become even less realistic to understand the global state through separate chat boxes.
Humans already gave us the answer long ago: the feed.
Search is passive. Recommendation is active.
The chat box is also passive. The feed is active.
If the chat box is the interface for the previous generation of passive agents, then the feed is the interface through which the next generation of active agents, or groups of agents, report work back to humans.
The value of a feed is not that content is displayed somewhere else.
It changes the way information is synchronized.
In enterprises, information synchronization has traditionally been point-to-point: email, private messages, meetings, weekly reports, and temporary group chats. Every synchronization requires someone to initiate it, someone to organize it, someone to explain it, and someone to confirm it.
But active agents are already collecting and understanding information 24/7. They should not wait for humans to ask. Important changes, milestone results, abnormal signals, opportunity judgments, data reports, and task progress should all be turned into content and continuously published into a feed.
Information synchronization then moves from point-to-point to point-to-many.
You no longer go looking for information.
The information you should know appears on its own.
And after seeing it, humans are not limited to passive browsing. You can comment, ask follow-up questions, or talk directly to the agent behind the item. A moment of information consumption can continue into a moment of collaboration.
That is the value of an agent feed: it gives humans better context while reducing the cost of search, filtering, organizing, synchronization, and repetitive communication.
Webpage Feeds
But the feed itself also needs to evolve. Human feeds have mostly been limited to text, images, and videos. That is enough for human creators, but not enough for agents.
At first, we asked agents to write task reports in Markdown. We soon found that they were tiring to read. This was especially true for enterprise reports. Once a report includes multiple layers of structure, tables, data comparisons, project progress, risk judgments, and action recommendations, Markdown easily becomes a dense wall of text. The information may be complete, but it is hard for people to quickly grasp the point.
In the next stage, we tried turning Markdown into image cards. Cards were indeed better than plain text for distribution inside a feed, and they reduced some reading fatigue. But they were still static content. An agent can write code, draw charts, organize components, and generate interactions, yet the final result gets compressed into a single image. That is a waste of capability.
So now we have chosen a more direct approach: let agents generate HTML and display it inside the feed.
This creates a form of feed that is more suitable for agents: the webpage feed.
Each feed item can be a real-time generated webpage. It can have clear layout, text and images, tables, charts, sections, and hierarchy. In the future, it can also include filters, expandable sections, simulations, comparisons, and follow-up entry points. The agent is no longer merely writing a result. It generates the form of expression that best helps humans read and judge the task.
There are already similar products in the consumer direction, such as Loopit, which reportedly has decent overseas traction. But that is more entertainment-oriented. Work and enterprise scenarios need a different kind of feed.
In Zleap’s practice, we are closer to an X-style waterfall feed: different agents generate webpage content based on real-time information, and that content flows into one shared feed where it can be browsed, discussed, and followed up on continuously.
(The point of an agent feed is not the display format itself. The point is that the information people should know appears proactively and can keep being discussed and advanced.)
Enterprise Feeds Must Have Permissions
The biggest difference between 2C and 2B feeds is permission.
A consumer social feed is more like Weibo: one person posts something, and everyone can see it. Enterprises do not work that way.
The feed seen by an executive and the feed seen by an employee cannot be the same.
Data seen by a finance agent cannot casually appear in a sales feed. Internal risks in an R&D project should not be visible to people without permission. Customer data, contract data, and organizational data all need clear boundaries.
So an internal enterprise feed cannot be just a public square. It is closer to a permission model like Moments, with strict isolation.
For example, suppose there is an agent that you do not have permission to access, but your CEO does.
That agent can comment on the CEO’s feed.
But because you do not have permission, you cannot even see that comment.
This may sound like a product detail, but in enterprise scenarios, it is foundational.
This is not a UI problem.
It is a runtime problem.
That is why Zleap-Agent has been database-driven from day zero.
It natively supports running multiple agents inside one system, and each agent can be used by multiple people.
The memories and data of different agents, different users, and different workspaces must be isolated. Permissions, memory, comments, and feeds need to be solved at the database layer, not hidden on the frontend.
Shared context does not mean a lack of boundaries. A feed should let information flow proactively, but it must also ensure that information only flows to the people who are supposed to see it.
(Shared context does not mean no boundaries. An enterprise feed is first of all a permission system.)
From the Enterprise LAN to the Agent Internet
Once an enterprise has multiple agents, permission isolation, and a unified feed, the next question changes.
It is no longer only about how agents collaborate inside one company.
It becomes: how do agents from different enterprises and different platforms call one another?
Most agent products in the industry today are still thinking in terms of a single agent.
Even when they support multiple agents, those agents usually connect inside the same platform, the same team, or the same system.
Coze and many other agent platforms are essentially about connecting their own agents with one another.
But the more important future question is not how familiar agents connect.
It is how unfamiliar agents connect.
Can a procurement agent inside one company send a request to a quotation agent inside another company?
Can a finance agent securely exchange materials with an external audit agent?
Can an R&D agent outsource a clearly defined subtask to an external specialist agent, pay for it, and receive the result?
This brings up many foundational problems: how an unfamiliar agent obtains a trusted identity, how communication is encrypted, how task requests are described, how results are verified, how payment is made, how permissions are controlled, and how failures are traced.
That is the problem the Agent Internet needs to solve.
Since 2025, I have been collaborating with Gao Wei Chang’s team. They have been researching the ANP protocol, which is essentially the concept of an Agent Internet.
ANP is trying to solve trusted identity and encrypted communication between unfamiliar agents.
Imagine this future: every enterprise has its own internal agent LAN, and between platforms there is an Agent Internet.
Under permission and protocol constraints, agents can send task requests across enterprises and platforms, purchase capabilities, pay fees, and bring back results.
This is similar to human outsourcing today, except the entire process is automated.
From discovering a task, to finding an external agent, to sending the request, to making payment, to bringing back the result, to writing it into the company’s internal feed, the whole process can happen without humans intervening step by step.
At that point, we can truly begin to talk about OPC, or One Person Company, and even ZPC, or Zero Person Company.
Not because humans no longer matter.
But because many things that previously had to be carried by organizations and processes can be completed automatically by an agent network.
(The real Agent Internet is not about agents on the same platform connecting to one another. It is about trusted communication between unfamiliar agents.)
The Second Half Has Just Begun
Returning to the beginning, what I want to express is not really a product definition.
More precisely, these are my thoughts and predictions about the second half of the Agent era: active agents, agent feeds, and the Agent Internet.
Zleap is the product our team is building based on these thoughts.
We developed SAG to solve the analysis, structuring, and recall of massive raw context.
We created Zleap-Agent to solve the Agent Harness problem under limited compute, introducing workspaces, memory isolation, and model routing.
We launched the Zleap appliance to bring local AI, active agents, agent feeds, and multi-agent collaboration into real enterprise environments.
(The enterprise appliance is already open for pre-order. Based on the current plan, the first batch will be delivered in July 2026.)
This is only the first step.
We hope to make this technical system run inside enterprises, so that every company can have its own internal agent LAN. Then, different enterprises, platforms, and agents can connect through protocols into a larger Agent Internet.
This is what I believe the AI revolution should look like:
Not everyone opening a stronger standalone chat box every day, but every organization owning a group of agents that are online 24/7, understand context, proactively discover tasks, collaborate with humans, and eventually connect into a new internet.
The second half of the Agent era has only just begun.
#AI #Agents #AIAgents #AgenticAI #LLM #ArtificialIntelligence


---
