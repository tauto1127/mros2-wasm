#include "rtps/discovery/ParticipantProxyData.h"
#include "rtps/entities/Participant.h"
#include "rtps/communication/UdpDriver.h"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace {

bool g_known_participant = false;

void append_header(ucdrBuffer &buffer, uint16_t parameter_id,
                   uint16_t length) {
  assert(ucdr_serialize_uint16_t(&buffer, parameter_id));
  assert(ucdr_serialize_uint16_t(&buffer, length));
}

void append_locator(ucdrBuffer &buffer, uint16_t parameter_id,
                    uint8_t address_last_octet) {
  const auto locator = rtps::FullLengthLocator::createUDPv4Locator(
      192, 168, 100, address_last_octet, 7400);
  append_header(buffer, parameter_id, sizeof(locator));
  assert(ucdr_serialize_array_uint8_t(
      &buffer, reinterpret_cast<const uint8_t *>(&locator), sizeof(locator)));
}

void append_guid(ucdrBuffer &buffer) {
  const rtps::GuidPrefix_t prefix{{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}};
  const rtps::EntityId_t entity{
      std::array<uint8_t, 3>{0, 0, 1},
      rtps::EntityKind_t::BUILD_IN_PARTICIPANT};
  append_header(buffer, rtps::SMElement::ParameterId::PID_PARTICIPANT_GUID,
                sizeof(prefix.id) + sizeof(entity.entityKey) + 1);
  assert(ucdr_serialize_array_uint8_t(&buffer, prefix.id.data(),
                                      prefix.id.size()));
  assert(ucdr_serialize_array_uint8_t(&buffer, entity.entityKey.data(),
                                      entity.entityKey.size()));
  assert(ucdr_serialize_uint8_t(
      &buffer, static_cast<uint8_t>(entity.entityKind)));
}

size_t make_spdp(uint8_t address_last_octet, uint8_t *storage,
                 size_t storage_size) {
  ucdrBuffer buffer;
  ucdr_init_buffer(&buffer, storage, storage_size);
  buffer.endianness = UCDR_LITTLE_ENDIANNESS;

  // Real SPDP announcements carry locators before the participant GUID.
  append_locator(buffer, rtps::SMElement::ParameterId::PID_DEFAULT_UNICAST_LOCATOR,
                 address_last_octet);
  append_locator(
      buffer, rtps::SMElement::ParameterId::PID_METATRAFFIC_UNICAST_LOCATOR,
      address_last_octet);
  append_guid(buffer);
  append_header(buffer, rtps::SMElement::ParameterId::PID_SENTINEL, 0);
  return ucdr_buffer_length(&buffer);
}

} // namespace

namespace rtps {

const ParticipantProxyData *Participant::findRemoteParticipant(
    const GuidPrefix_t &) {
  static ParticipantProxyData known;
  return g_known_participant ? &known : nullptr;
}

bool UdpDriver::isSameSubnet(ip4_addr_t) { return true; }
bool UdpDriver::isMulticastAddress(ip4_addr_t) { return false; }

} // namespace rtps

int main() {
  uint8_t first_storage[256]{};
  uint8_t second_storage[256]{};
  const auto first_size =
      make_spdp(5, first_storage, sizeof(first_storage));
  const auto second_size =
      make_spdp(6, second_storage, sizeof(second_storage));

  rtps::ParticipantProxyData proxy;
  ucdrBuffer first;
  ucdr_init_buffer(&first, first_storage, first_size);
  first.endianness = UCDR_LITTLE_ENDIANNESS;
  assert(proxy.readFromUcdrBuffer(first, reinterpret_cast<rtps::Participant *>(
                                          static_cast<uintptr_t>(1))));
  assert(proxy.m_defaultUnicastLocatorList[0].address[3] == 5);

  g_known_participant = true;
  ucdrBuffer second;
  ucdr_init_buffer(&second, second_storage, second_size);
  second.endianness = UCDR_LITTLE_ENDIANNESS;
  assert(proxy.readFromUcdrBuffer(second, reinterpret_cast<rtps::Participant *>(
                                           static_cast<uintptr_t>(1))));
  const auto updated = proxy.m_defaultUnicastLocatorList[0].address[3];

  std::printf("same-guid locator update: old=192.168.100.5 new=192.168.100.%u\n",
              static_cast<unsigned>(updated));
  return updated == 6 ? 0 : 1;
}
