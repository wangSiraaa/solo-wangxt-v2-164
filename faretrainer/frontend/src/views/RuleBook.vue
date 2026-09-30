<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({ versions: { type: Array, default: () => [] } })
const fares = ref([])
const filterVersion = ref('')

onMounted(async () => {
  fares.value = await api.fares()
})

function shownFares() {
  if (!filterVersion.value) return fares.value
  return fares.value.filter((f) => f.rule_version === filterVersion.value)
}
</script>

<template>
  <div class="grid">
    <div class="card">
      <h2>规则版本（试算结果固定到版本，可追溯）</h2>
      <div class="scenario-chips">
        <button class="chip" @click="filterVersion = ''">全部</button>
        <button
          v-for="v in props.versions"
          :key="v.version"
          class="chip"
          @click="filterVersion = v.version"
        >{{ v.version }}（{{ v.effective_from }} 生效）</button>
      </div>
      <table v-if="props.versions.length">
        <thead>
          <tr><th>版本</th><th>发布时间(UTC)</th><th>生效日</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="v in props.versions" :key="v.version">
            <td><code class="mono">{{ v.version }}</code></td>
            <td>{{ v.published_at.replace('T', ' ').slice(0, 16) }}</td>
            <td>{{ v.effective_from }}</td>
            <td>{{ v.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>运价与规则表达式</h2>
      <p class="muted small">
        规则用沙箱表达式（非任意代码）：比较 / and / or / in，
        变量来自引擎上下文（转机分钟、停留次数、停留日、舱位、跨本地日期数等）。
        <b>scope</b> 标明规则在组件内部还是组件拼接的衔接点求值。
      </p>

      <div v-for="f in shownFares()" :key="f.id" class="candidate">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px">
          <strong>
            <code class="mono">{{ f.fare_code }}</code>
            {{ f.origin }}-{{ f.destination }} {{ f.fare_type }}
            <span class="badge neutral">{{ f.carrier }}</span>
          </strong>
          <span>
            <span class="money">¥{{ f.price }}</span>
            <span class="badge" :class="f.end_on_end_allowed ? 'ok' : 'fail'">
              {{ f.end_on_end_allowed ? '允许联程组合' : '禁止联程组合' }}
            </span>
            <span class="badge neutral">提前 {{ f.advance_purchase_days }} 天</span>
            <span class="badge neutral">改签费 ¥{{ f.change_fee }}</span>
            <span class="badge neutral">{{ f.rule_version }}</span>
          </span>
        </div>
        <div class="small muted" style="margin:4px 0">
          路由腿：
          <span v-for="(l, i) in f.route" :key="i">
            {{ l.from }}-{{ l.to }}<span v-if="i < f.route.length - 1"> → </span>
          </span>
          ｜ 适用舱位：{{ f.booking_classes.join(' / ') }}
        </div>
        <table style="margin-top:6px">
          <thead>
            <tr><th>规则码</th><th>类别</th><th>scope</th><th>表达式</th><th>含义</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in f.rules" :key="r.code">
              <td><code class="mono">{{ r.code }}</code></td>
              <td>{{ r.category_label }}</td>
              <td><span class="badge neutral">{{ r.scope }}</span></td>
              <td><div class="expr">{{ r.expression }}</div></td>
              <td>{{ r.message_zh }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
