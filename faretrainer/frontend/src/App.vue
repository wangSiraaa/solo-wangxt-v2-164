<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api.js'
import PriceLab from './views/PriceLab.vue'
import RuleBook from './views/RuleBook.vue'
import Tickets from './views/Tickets.vue'
import DataBrowser from './views/DataBrowser.vue'

const tab = ref('price')
const versions = ref([])
const globalError = ref('')

onMounted(async () => {
  try {
    versions.value = await api.versions()
  } catch (e) {
    globalError.value = '无法连接后端 API（请确认 Django 已启动）'
  }
})
</script>

<template>
  <header class="topbar">
    <h1>
      多航段运价组合培训沙箱
      <span class="sandbox-badge">虚构数据 · 不出票 · 不接订座</span>
    </h1>
    <p>
      票价来自运价组件（一个组件可覆盖多段），不是逐段价格相加；
      停留 / 转机 / 最短最长停留 / 联程组合按规则表达式判断，
      时间按机场本地日历与 UTC 双重校验。
    </p>
  </header>

  <nav class="tabs">
    <button :class="{ active: tab === 'price' }" @click="tab = 'price'">
      试算实验室
    </button>
    <button :class="{ active: tab === 'rules' }" @click="tab = 'rules'">
      运价规则书
    </button>
    <button :class="{ active: tab === 'tickets' }" @click="tab = 'tickets'">
      培训票与改签
    </button>
    <button :class="{ active: tab === 'data' }" @click="tab = 'data'">
      航班 / 舱位 / 税
    </button>
  </nav>

  <main>
    <p v-if="globalError" class="banner fail">{{ globalError }}</p>

    <PriceLab v-if="tab === 'price'" :versions="versions" />
    <RuleBook v-else-if="tab === 'rules'" :versions="versions" />
    <Tickets v-else-if="tab === 'tickets'" />
    <DataBrowser v-else />
  </main>
</template>
