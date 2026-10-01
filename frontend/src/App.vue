<script setup>
import { ref } from 'vue'
import QuoteWorkbench from './components/QuoteWorkbench.vue'
import RebookWorkbench from './components/RebookWorkbench.vue'
import RulesBrowser from './components/RulesBrowser.vue'

const tab = ref('quote')
const tabs = [
  { key: 'quote', label: '多航段报价' },
  { key: 'rebook', label: '改签试算' },
  { key: 'rules', label: '运价规则版本' },
]
</script>

<template>
  <header style="margin-bottom: 8px">
    <h1>机票服务培训台：多航段如何组合成一个票价</h1>
    <p class="muted small">
      核心口径：多航段票价 = 一个或多个<b>运价组件（fare component）</b>之和，
      来回程（RT）运价一个价覆盖去+回两段，<b>不是逐段公布价简单相加</b>；
      停留/转机/最短最长停留/联程组合按规则表达式判定，时间以
      <b>UTC 物理时刻</b>与<b>机场当地日历</b>双重校验。
      全部航班、舱位、运价、税费均为<b>虚构教学数据</b>，系统不接入真实订座/出票，
      不生成真实购票、换开或退款指令。
    </p>
  </header>

  <div class="tabs">
    <button
      v-for="t in tabs"
      :key="t.key"
      :class="{ active: tab === t.key }"
      @click="tab = t.key"
    >{{ t.label }}</button>
  </div>

  <QuoteWorkbench v-if="tab === 'quote'" />
  <RebookWorkbench v-else-if="tab === 'rebook'" />
  <RulesBrowser v-else />

  <footer class="small muted" style="margin-top: 30px">
    金额链路：PostgreSQL Numeric → Django DecimalField / Python Decimal（quantize 到分）
    → JSON 字符串 → 前端 decimal.js。全程不使用二进制浮点。
  </footer>
</template>
