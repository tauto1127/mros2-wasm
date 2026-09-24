#define private public
#include "rtps/entities/Participant.h"
#undef private

#include "lwip/sys.h"
#include "rtps/communication/UdpDriver.h"
#include "rtps/discovery/SEDPAgent.h"

#include <cassert>
#include <cstdint>
#include <cstdio>

extern "C" err_t sys_mutex_new(sys_mutex_t *) { return ERR_OK; }
extern "C" void sys_mutex_lock(sys_mutex_t *) {}
extern "C" void sys_mutex_unlock(sys_mutex_t *) {}
extern "C" void sys_mutex_free(sys_mutex_t *) {}
extern "C" uint32_t osKernelGetTickCount(void) { return 0; }
extern "C" char *ip4addr_ntoa(const ip4_addr_t *) {
  static char address[] = "192.168.100.6";
  return address;
}

namespace rtps {

bool UdpDriver::isSameSubnet(ip4_addr_t) { return true; }
bool UdpDriver::isMulticastAddress(ip4_addr_t) { return false; }

void SEDPAgent::removeUnmatchedEntitiesOfParticipant(
    const GuidPrefix_t &) {}
void SEDPAgent::addWriter(Writer &) {}
void SEDPAgent::addReader(Reader &) {}

struct ProbeWriter final : Writer {
  uint32_t set_unsent_count = 0;
  uint32_t added_reader_count = 0;
  uint32_t removed_participant_count = 0;
  LocatorIPv4 last_reader_locator{};

  bool addNewMatchedReader(const ReaderProxy &proxy) override {
    ++added_reader_count;
    last_reader_locator = proxy.remoteLocator;
    return true;
  }
  void removeReader(const Guid_t &) override {}
  void removeReaderOfParticipant(const GuidPrefix_t &) override {
    ++removed_participant_count;
  }
  void progress() override {}
  const CacheChange *newChange(ChangeKind_t, const uint8_t *, DataSize_t)
      override {
    return nullptr;
  }
  const CacheChange *newChangeCallback(ChangeKind_t,
                                       CacheChange::SerializerCallback,
                                       FragDataSize_t) override {
    return nullptr;
  }
  const CacheChange *newChangeIdentify(ChangeKind_t, const uint8_t *, DataSize_t,
                                       Sample_Indetify) override {
    return nullptr;
  }
  void setAllChangesToUnsent() override { ++set_unsent_count; }
  void onNewAckNack(const SubmessageAckNack &,
                    const GuidPrefix_t &) override {}
};

struct ProbeReader final : Reader {
  uint32_t added_writer_count = 0;
  uint32_t removed_participant_count = 0;
  LocatorIPv4 last_writer_locator{};

  void newChange(const ReaderCacheChange &) override {}
  void registerCallback(ddsReaderCallback_fp, void *) override {}
  bool onNewHeartbeat(const SubmessageHeartbeat &,
                      const GuidPrefix_t &) override {
    return true;
  }
  bool addNewMatchedWriter(const WriterProxy &proxy) override {
    ++added_writer_count;
    last_writer_locator = proxy.remoteLocator;
    return true;
  }
  void removeWriter(const Guid_t &) override {}
  void removeWriterOfParticipant(const GuidPrefix_t &) override {
    ++removed_participant_count;
  }
};

} // namespace rtps

int main() {
  const rtps::GuidPrefix_t local_prefix{{9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9,
                                         9}};
  const rtps::GuidPrefix_t peer_prefix{{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
                                        12}};
  const rtps::EntityId_t peer_entity{
      std::array<uint8_t, 3>{0, 0, 1},
      rtps::EntityKind_t::BUILD_IN_PARTICIPANT};

  rtps::Participant participant(local_prefix, 0);
  rtps::ParticipantProxyData old_data{{peer_prefix, peer_entity}};
  old_data.m_defaultUnicastLocatorList[0] =
      rtps::LocatorIPv4(rtps::FullLengthLocator::createUDPv4Locator(
          192, 168, 100, 5, 7400));
  old_data.m_metatrafficUnicastLocatorList[0] =
      rtps::LocatorIPv4(rtps::FullLengthLocator::createUDPv4Locator(
          192, 168, 100, 5, 7410));
  old_data.m_availableBuiltInEndpoints = 0x3f;
  assert(participant.addNewRemoteParticipant(old_data));

  rtps::SPDPAgent &agent = participant.getSPDPAgent();
  rtps::ProbeWriter spdp_writer;
  rtps::ProbeWriter sedp_pub_writer;
  rtps::ProbeWriter sedp_sub_writer;
  rtps::ProbeReader spdp_reader;
  rtps::ProbeReader sedp_pub_reader;
  rtps::ProbeReader sedp_sub_reader;
  assert(participant.addWriter(&spdp_writer) != nullptr);
  assert(participant.addWriter(&sedp_pub_writer) != nullptr);
  assert(participant.addWriter(&sedp_sub_writer) != nullptr);
  assert(participant.addReader(&spdp_reader) != nullptr);
  assert(participant.addReader(&sedp_pub_reader) != nullptr);
  assert(participant.addReader(&sedp_sub_reader) != nullptr);

  agent.mp_participant = &participant;
  agent.m_buildInEndpoints.spdpWriter = &spdp_writer;
  agent.m_buildInEndpoints.sedpPubWriter = &sedp_pub_writer;
  agent.m_buildInEndpoints.sedpSubWriter = &sedp_sub_writer;
  agent.m_buildInEndpoints.sedpPubReader = &sedp_pub_reader;
  agent.m_buildInEndpoints.sedpSubReader = &sedp_sub_reader;
  agent.m_proxyDataBuffer = old_data;
  agent.m_proxyDataBuffer.m_defaultUnicastLocatorList[0] =
      rtps::LocatorIPv4(rtps::FullLengthLocator::createUDPv4Locator(
          192, 168, 100, 6, 7400));
  agent.m_proxyDataBuffer.m_metatrafficUnicastLocatorList[0] =
      rtps::LocatorIPv4(rtps::FullLengthLocator::createUDPv4Locator(
          192, 168, 100, 6, 7410));

  agent.processProxyData();

  const auto *updated = participant.findRemoteParticipant(peer_prefix);
  assert(updated != nullptr);
  assert(participant.getRemoteParticipantCount() == 1);
  assert(updated->m_defaultUnicastLocatorList[0].address[3] == 6);
  assert(spdp_writer.set_unsent_count == 1);
  assert(spdp_writer.removed_participant_count == 1);
  assert(sedp_pub_writer.removed_participant_count == 1);
  assert(sedp_sub_writer.removed_participant_count == 1);
  assert(spdp_reader.removed_participant_count == 1);
  assert(sedp_pub_reader.removed_participant_count == 1);
  assert(sedp_sub_reader.removed_participant_count == 1);
  assert(sedp_pub_reader.added_writer_count == 1);
  assert(sedp_sub_reader.added_writer_count == 1);
  assert(sedp_pub_writer.added_reader_count == 1);
  assert(sedp_sub_writer.added_reader_count == 1);
  assert(sedp_pub_reader.last_writer_locator.address[3] == 6);
  assert(sedp_sub_reader.last_writer_locator.address[3] == 6);
  assert(sedp_pub_writer.last_reader_locator.address[3] == 6);
  assert(sedp_sub_writer.last_reader_locator.address[3] == 6);

  std::printf(
      "same-guid registration update: old=192.168.100.5 new=192.168.100.%u "
      "participants=%u endpoint_proxies_rebuilt=4\n",
      static_cast<unsigned>(updated->m_defaultUnicastLocatorList[0].address[3]),
      static_cast<unsigned>(participant.getRemoteParticipantCount()));
  return 0;
}
