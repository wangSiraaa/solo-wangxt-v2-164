<script setup>
import { onMounted, ref } from 'vue'
import { api, cny } from '../api'

const fares = ref([])
const selectedFareId = ref(null)
const versions = ref([])
const loading = ref(false)

onMounted(async () => {
  fares.value = await api.fares()
  const yrt = fares.value.find((f) => f.fare_code === 'YRT')
  if (yrt) await pick(yrt.id)
})

async function pick(id) {
  selectedFareId.value = id
  loading.value = true
  versions.value = await api.fareVersions(id)
  loading.value = false
}
</script>

<template>
  <div>
    <div class="panel">
      <h3>规则版本库（试算结果中的 version-id 都可回到这里核对）</h3>
      <div class="tabs">
        <button
          v-for="f in fares"
          :key="f.id"
          :class="{ active: f.id === selectedFareId }"
          @click="pick(f.id)"
        >
          {{ f.fare_code }} {{ f.origin }}-{{ f.destination }} {{ f.direction }} {{ f.rbd }}
          · {{ cny(f.amount_cny) }}
        </button>
      </div>
    </div>

    <div v-for="v in versions" :key="v.id" class="panel" :class="{ tight: !v.active_fare_uses_this }">
      <div class="row" style="justify-content: space-between">
        <div>
          <span class="badge" :class="v.active_fare_uses_this ? 'ok' : 'warn'">
            {{ v.active_fare_uses_this ? '当前生效版本' : '历史版本（已归档）' }}
          </span>
          <b style="margin-left: 8px; font-size: 15px">
            {{ v.fare_code }} {{ v.fare_od }} — 规则 v{{ v.version }}
          </b>
        </div>
        <div class="small muted">
          版本主键 #{{ v.id }} · 发布 {{ v.published_at.slice(0, 10) }}<br />
          {{ v.note }}
        </div>
      </div>
      <table style="margin-top: 10px">
        <thead>
          <tr><th>规则类型</th><th>说明</th><th>示例表达式</th><th>手续费</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in v.rules" :key="r.id">
            <td><span class="badge info">{{ r.code }}</span></td>
            <td class="small">{{ r.description }}</td>
            <td class="expr">{{ r.expression }}</td>
            <td class="mono">{{ r.fee_cny != null ? cny(r.fee_cny) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
