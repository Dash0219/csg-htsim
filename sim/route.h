// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-        
#ifndef ROUTE_H
#define ROUTE_H

/*
 * A Route, carried by packets, to allow routing
 */

#include "config.h"
#include <list>
#include <vector>

#include <memory>
#include <unordered_map>
#include <cstdint>
#include <algorithm> // for std::find

struct RouteINT_hop {
    uint32_t hop_id;
    simtime_picosec timestamp;   // simtime_picosec is an integer type; store as uint64_t to avoid header cycles
    uint32_t queue_len;
};

typedef uint32_t packetid_t;

class PacketSink;
class Packet;
class Route {
  public:
    Route();
    Route(int size);
    Route(const Route& orig, PacketSink& dst);
    Route* clone() const;
    inline PacketSink* at(size_t n) const {return _sinklist.at(n);}
    void push_back(PacketSink* sink) {
        assert(sink != NULL);
        _sinklist.push_back(sink);
        update_hopcount(sink);
    }
    void push_at(PacketSink* sink,int id) {
        _sinklist.insert(_sinklist.begin()+id, sink);
            update_hopcount(sink);
    }
    void push_front(PacketSink* sink) {
        _sinklist.insert(_sinklist.begin(), sink);
            update_hopcount(sink);
    }
    void add_endpoints(PacketSink *src, PacketSink* dst);
    inline size_t size() const {return _sinklist.size();}
    typedef vector<PacketSink*>::const_iterator const_iterator;
    inline const_iterator begin() const {return _sinklist.begin();}
    inline const_iterator end() const {return _sinklist.end();}
    void set_reverse(Route* reverse) {_reverse = reverse;}
    inline const Route* reverse() const {return _reverse;}
    void set_path_id(int path_id, int no_of_paths) {
        _path_id = path_id;
        _no_of_paths = no_of_paths;
    }
    inline int path_id() const {return _path_id;}
    inline int no_of_paths() const {return _no_of_paths;}
    inline uint32_t hop_count() const {return _hop_count;}

    vector<PacketSink*> _sinklist;

    // void add_int_hop(uint32_t hop,
    //                  simtime_picosec ts,
    //                  uint32_t qlen) const;

    // const std::vector<RouteINT_hop>& get_int_trace() const;
    // void clear_int_trace() const;

  private:
    void update_hopcount(PacketSink* sink);
    uint32_t _hop_count;
    Route* _reverse;
    int _path_id; //path identifier for this path
    int _no_of_paths; //total number of paths sender is using

    // mutable std::vector<RouteINT_hop> _int_trace;
};
//typedef vector<PacketSink*> route_t;
typedef Route route_t;
typedef vector<route_t*> routes_t;

void check_non_null(Route* rt);

#endif